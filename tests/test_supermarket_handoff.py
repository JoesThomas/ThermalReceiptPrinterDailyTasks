import json
from unittest import TestCase
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from meals import supermarket as shop


class SupermarketTests(TestCase):
    def test_merges_exact_amounts_and_preserves_special_ingredient_names(self):
        visits = [
            {"items": [{"requirements": ["120g gluten-free pasta"], "pantry": False}]},
            {
                "items": [
                    {"requirements": ["80g gluten-free pasta"], "pantry": True},
                    {"requirements": ["salt to taste"], "pantry": False},
                ]
            },
        ]
        rows, fingerprint = shop.review(visits, "waitrose")
        self.assertEqual(
            [row["amount"] for row in rows], ["200g gluten-free pasta", "salt to taste"]
        )
        self.assertTrue(rows[0]["pantry"])
        self.assertFalse(rows[1]["measured"])
        self.assertEqual(
            parse_qs(urlsplit(rows[0]["search"]).query)["searchTerm"],
            ["gluten-free pasta"],
        )
        self.assertNotEqual(fingerprint, shop.review(visits, "tesco")[1])

    def test_links_encode_terms_as_data_for_all_six_retailers(self):
        for retailer in shop.RETAILERS:
            with self.subTest(retailer=retailer):
                url = urlsplit(shop.search_url(retailer, "beans & oil/#"))
                self.assertEqual(url.scheme, "https")
                self.assertEqual(url.netloc, urlsplit(shop.SHOPS_HOME[retailer]).netloc)
                self.assertEqual(url.fragment, "")
                self.assertNotIn(" ", url.geturl())

    @patch.dict("os.environ", {shop.TOKEN_ENV: "fixture-token"})
    @patch.object(shop.requests, "post")
    def test_partner_payload_is_only_reviewed_items_and_chosen_retailer(self, post):
        landing = shop.TRANSFER_URL + "/" + "a" * 32 + "/landing"
        response = MagicMock(status_code=200)
        response.iter_content.return_value = [
            json.dumps({"landingUrl": landing}).encode()
        ]
        post.return_value.__enter__.return_value = response
        self.assertEqual(shop.transfer("ocado", ["200g gluten-free pasta"]), landing)
        args, kwargs = post.call_args
        self.assertEqual(args, (shop.TRANSFER_URL,))
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["headers"]["Authorization"], "Token fixture-token")
        self.assertEqual(
            kwargs["json"],
            dict(
                country="GB",
                language="en",
                allowedRetailers=["GB:Ocado"],
                rawItems=["200g gluten-free pasta"],
            ),
        )

    @patch.dict("os.environ", {shop.TOKEN_ENV: "fixture-token"})
    @patch.object(shop.requests, "post")
    def test_rejects_unsupported_empty_and_unrecognised_partner_response(self, post):
        with self.assertRaises(shop.HandoffError):
            shop.transfer("asda", ["1 potato"])
        with self.assertRaises(shop.HandoffError):
            shop.transfer("tesco", [])
        post.assert_not_called()
        response = MagicMock(status_code=200)
        response.iter_content.return_value = [
            b'{"landingUrl":"https://graph.whisk.com.example/test"}'
        ]
        post.return_value.__enter__.return_value = response
        with self.assertRaises(shop.HandoffError):
            shop.transfer("tesco", ["1 potato"])

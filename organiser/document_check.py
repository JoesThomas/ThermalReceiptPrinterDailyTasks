"""Isolated, bounded parsing of uploads. Input/output are pipes, never public files."""
import io
import sys
import warnings

MAX = 5 * 1024 * 1024


def check(raw, suffix):
    if not raw or len(raw) > MAX:
        raise ValueError()
    if suffix in ('png', 'jpg', 'jpeg'):
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = 10_000_000
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        image = Image.open(io.BytesIO(raw))
        expected = 'PNG' if suffix == 'png' else 'JPEG'
        if image.format != expected or getattr(image, 'n_frames', 1) != 1 or image.width * image.height > 10_000_000:
            raise ValueError()
        image.verify()
        image = Image.open(io.BytesIO(raw)).convert('RGB')
        clean = Image.new('RGB', image.size)
        clean.paste(image)
        output = io.BytesIO()
        clean.save(output, format=expected)
        if len(output.getvalue()) > MAX:
            raise ValueError()
        return output.getvalue()
    if suffix != 'pdf' or not raw.startswith(b'%PDF-') or b'%%EOF' not in raw[-1024:]:
        raise ValueError()
    from pypdf import PdfReader, filters
    from pypdf.generic import DictionaryObject, ArrayObject, IndirectObject
    filters.ZLIB_MAX_OUTPUT_LENGTH = 8_000_000
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or len(reader.pages) > 100 or sum(len(v) for v in reader.xref.values()) > 5000:
        raise ValueError()
    forbidden = {'/A', '/AcroForm', '/AF', '/Collection', '/Movie', '/Sound', '/Rendition', '/GoToE', '/Filespec', '/JS', '/JavaScript', '/AA', '/OpenAction', '/Launch', '/EmbeddedFiles', '/EmbeddedFile',
                 '/RichMedia', '/XFA', '/SubmitForm', '/ImportData', '/GoToR', '/URI'}
    seen = set()
    def walk(obj, depth=0):
        if depth > 30:
            raise ValueError()
        if isinstance(obj, IndirectObject):
            identity = (obj.idnum, obj.generation)
            if identity in seen:
                return
            seen.add(identity)
            obj = obj.get_object()
        if isinstance(obj, DictionaryObject):
            if any(str(k) in forbidden for k in obj) or str(obj.get('/Type', '')) in forbidden or str(obj.get('/S', '')) in forbidden:
                raise ValueError()
            for v in obj.values():
                walk(v, depth+1)
        elif isinstance(obj, ArrayObject):
            for v in obj:
                walk(v, depth+1)
    for generation, objects in reader.xref.items():
        for identifier in objects:
            if identifier:
                walk(IndirectObject(identifier, generation, reader))
    walk(reader.trailer)
    return raw


if __name__ == '__main__':
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
        if sys.platform != 'darwin':
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        sys.stdout.buffer.write(check(sys.stdin.buffer.read(MAX+1), sys.argv[1]))
    except Exception:
        raise SystemExit(2) from None

(() => {
    const root = document.querySelector("[data-progress-key]");
    if (!root) return;

    const steps = [...root.querySelectorAll("[data-step]")];
    const ingredients = [...root.querySelectorAll("[data-ingredient]")];
    const key = "receipt-cooking:" + root.dataset.progressKey;
    let progress = {};
    try {
        progress = JSON.parse(sessionStorage.getItem(key)) || {};
    } catch { /* The controls also work without browser storage. */ }
    let step = Number.isInteger(progress.step) ? Math.max(0, Math.min(steps.length - 1, progress.step)) : 0;
    let showAll = false;
    const status = document.querySelector("#step-status");
    const previous = document.querySelector("#previous-step");
    const next = document.querySelector("#next-step");
    const toggle = document.querySelector("#all-steps");

    const save = () => {
        try {
            sessionStorage.setItem(key, JSON.stringify({
                step,
                checked: ingredients.filter(input => input.checked).map(input => input.dataset.ingredient),
            }));
        } catch { /* Progress remains available in the current view. */ }
    };
    const render = () => {
        steps.forEach((item, index) => { item.hidden = !showAll && step !== index; });
        status.textContent = showAll ? `Showing all ${steps.length} steps` : `Step ${step + 1} of ${steps.length}`;
        previous.disabled = step === 0;
        next.disabled = step === steps.length - 1;
        toggle.setAttribute("aria-pressed", String(showAll));
        toggle.textContent = showAll ? "Show one step" : "Show all steps";
        document.querySelector("#step-controls").hidden = showAll || steps.length < 2;
    };
    const move = (offset) => {
        step = Math.max(0, Math.min(steps.length - 1, step + offset));
        render();
        save();
        if (steps[step].getBoundingClientRect().top < 0) {
            document.querySelector("#method").scrollIntoView({ block: "start" });
        }
    };
    previous.addEventListener("click", () => move(-1));
    next.addEventListener("click", () => move(1));
    toggle.addEventListener("click", () => { showAll = !showAll; render(); });
    status.hidden = false;
    toggle.hidden = steps.length < 2;
    for (const input of ingredients) {
        input.checked = Array.isArray(progress.checked) && progress.checked.includes(input.dataset.ingredient);
        input.addEventListener("change", save);
    }
    const reset = document.querySelector("#reset-ingredients");
    reset.hidden = !ingredients.length;
    reset.addEventListener("click", () => {
        ingredients.forEach(input => { input.checked = false; });
        save();
    });
    render();

    const awake = document.querySelector("#keep-awake");
    const awakeStatus = document.querySelector("#awake-status");
    if (!("wakeLock" in navigator)) return;
    let requested = false;
    let pending = false;
    let lock = null;
    const showStatus = (message) => {
        awakeStatus.textContent = message;
        awakeStatus.hidden = !message;
        awake.setAttribute("aria-pressed", String(requested));
    };
    const enable = async () => {
        if (!requested || pending || lock || document.visibilityState !== "visible") return;
        pending = true;
        try {
            const held = await navigator.wakeLock.request("screen");
            if (!requested) {
                await held.release();
                return;
            }
            lock = held;
            showStatus("Screen stays awake while this page is visible.");
            held.addEventListener("release", () => {
                if (lock === held) lock = null;
                if (requested) showStatus("Screen lock paused.");
            }, { once: true });
        } catch {
            requested = false;
            showStatus("Screen lock unavailable. Check your display settings.");
        } finally {
            pending = false;
        }
    };
    awake.hidden = false;
    awake.addEventListener("click", () => {
        requested = !requested;
        showStatus("");
        if (requested) {
            enable();
        } else if (lock) {
            lock.release().catch(() => {});
        }
    });
    document.addEventListener("visibilitychange", enable);
})();

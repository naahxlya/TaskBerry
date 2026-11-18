(() => {
    "use strict";

    const STORAGE_KEY = "taskberry-theme";
    const root = document.documentElement;

    function normalizeTheme(value) {
        return value === "dark" ? "dark" : "light";
    }

    function readSavedTheme() {
        try {
            return normalizeTheme(localStorage.getItem(STORAGE_KEY));
        } catch (error) {
            console.warn("Não foi possível recuperar o tema salvo.", error);
            return "light";
        }
    }

    function updateThemeButton(theme) {
        const button = document.getElementById("theme-toggle");
        if (!button) return;

        const dark = theme === "dark";
        button.innerHTML = dark
            ? '<i class="bi bi-sun" aria-hidden="true"></i><span>Modo claro</span>'
            : '<i class="bi bi-moon" aria-hidden="true"></i><span>Modo escuro</span>';

        button.setAttribute("aria-pressed", String(dark));
        button.setAttribute("aria-label", dark ? "Ativar modo claro" : "Ativar modo escuro");
        button.title = dark ? "Ativar modo claro" : "Ativar modo escuro";
    }

    function applyTheme(theme, persist = true) {
        const selected = normalizeTheme(theme);

        root.setAttribute("data-theme", selected);
        root.setAttribute("data-bs-theme", selected);
        root.classList.toggle("theme-dark", selected === "dark");
        root.classList.toggle("theme-light", selected === "light");

        if (document.body) {
            document.body.setAttribute("data-theme", selected);
            document.body.classList.toggle("theme-dark", selected === "dark");
            document.body.classList.toggle("theme-light", selected === "light");
        }

        if (persist) {
            try {
                localStorage.setItem(STORAGE_KEY, selected);
            } catch (error) {
                console.warn("Não foi possível salvar a preferência de tema.", error);
            }
        }

        updateThemeButton(selected);
        return selected;
    }

    // Disponibiliza uma API única para o restante da aplicação.
    window.TaskBerryTheme = {
        apply: applyTheme,
        toggle: function () {
            const current = root.getAttribute("data-theme") || readSavedTheme();
            return applyTheme(current === "dark" ? "light" : "dark");
        },
        current: function () {
            return root.getAttribute("data-theme") || "light";
        }
    };

    applyTheme(readSavedTheme(), false);

    function initializeThemeControls() {
        updateThemeButton(root.getAttribute("data-theme") || "light");
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initializeThemeControls, { once: true });
    } else {
        initializeThemeControls();
    }

    // Delegação evita perder o clique se o conteúdo do botão for atualizado.
    document.addEventListener("click", function (event) {
        const button = event.target.closest("#theme-toggle");
        if (!button) return;

        event.preventDefault();
        window.TaskBerryTheme.toggle();
    });
})();

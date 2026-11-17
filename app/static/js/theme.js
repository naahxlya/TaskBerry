
(() => {
    "use strict";

    const STORAGE_KEY = "taskberry-theme";
    const root = document.documentElement;

    function getSavedTheme() {
        try {
            return localStorage.getItem(STORAGE_KEY) === "dark"
                ? "dark"
                : "light";
        } catch (error) {
            return "light";
        }
    }

    function updateThemeButton(theme) {
        const button = document.getElementById("theme-toggle");
        if (!button) return;

        const isDark = theme === "dark";

        button.innerHTML = isDark
            ? '<i class="bi bi-sun" aria-hidden="true"></i><span>Modo claro</span>'
            : '<i class="bi bi-moon" aria-hidden="true"></i><span>Modo escuro</span>';

        button.setAttribute("aria-pressed", String(isDark));

        button.setAttribute(
            "aria-label",
            isDark ? "Ativar modo claro" : "Ativar modo escuro"
        );
    }

    function applyTheme(theme, save = true) {
        const selectedTheme = theme === "dark" ? "dark" : "light";

        root.setAttribute("data-theme", selectedTheme);
        root.setAttribute("data-bs-theme", selectedTheme);

        if (save) {
            try {
                localStorage.setItem(STORAGE_KEY, selectedTheme);
            } catch (error) {
                console.warn(
                    "Não foi possível salvar o tema escolhido.",
                    error
                );
            }
        }

        updateThemeButton(selectedTheme);
    }

    // Mantém o tema aplicado entre páginas e visitas.
    applyTheme(getSavedTheme(), false);

    document.addEventListener("DOMContentLoaded", () => {
        updateThemeButton(
            root.getAttribute("data-theme") || "light"
        );

        const button = document.getElementById("theme-toggle");

        if (!button) return;

        button.addEventListener("click", () => {
            const currentTheme = root.getAttribute("data-theme");

            applyTheme(
                currentTheme === "dark" ? "light" : "dark"
            );
        });
    });
})();
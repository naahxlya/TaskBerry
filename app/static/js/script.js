document.addEventListener("DOMContentLoaded", function () {

    // Mostrar ou ocultar senhas
    const passwordButtons = document.querySelectorAll(
        "[data-toggle-password]"
    );

    passwordButtons.forEach(function (button) {

        button.addEventListener("click", function () {

            const inputId = button.dataset.togglePassword;
            const passwordInput = document.getElementById(inputId);

            if (!passwordInput) return;

            const showing = passwordInput.type === "text";

            passwordInput.type = showing ? "password" : "text";

            button.innerHTML = showing
                ? '<i class="bi bi-eye-slash"></i>'
                : '<i class="bi bi-eye"></i>';

            button.setAttribute(
                "aria-label",
                showing ? "Mostrar senha" : "Ocultar senha"
            );

        });

    });

    // Compatibilidade com o botão antigo da tela de login
    const loginButton = document.getElementById("togglePassword");
    const loginPassword = document.getElementById("senha");

    if (loginButton && loginPassword) {

        loginButton.addEventListener("click", function () {

            const showing = loginPassword.type === "text";

            loginPassword.type = showing ? "password" : "text";

            loginButton.innerHTML = showing
                ? '<i class="bi bi-eye-slash"></i>'
                : '<i class="bi bi-eye"></i>';

            loginButton.setAttribute(
                "aria-label",
                showing ? "Mostrar senha" : "Ocultar senha"
            );

        });

    }

});


document.addEventListener("DOMContentLoaded", function () {

    const sidebar = document.getElementById("sidebar");
    const sidebarToggle = document.getElementById("sidebarToggle");

    if (sidebar && sidebarToggle) {

        sidebarToggle.addEventListener("click", function () {
            sidebar.classList.toggle("open");
        });

        document.addEventListener("click", function (event) {

            const clicouNoMenu = sidebar.contains(event.target);
            const clicouNoBotao = sidebarToggle.contains(event.target);

            if (!clicouNoMenu && !clicouNoBotao) {
                sidebar.classList.remove("open");
            }

        });

    }

});


/* =========================================
   TASKBERRY - MATERIAIS
========================================= */

document.addEventListener("DOMContentLoaded", function () {

    // Evita envios duplicados nos formulários dos modais de materiais.
    const formulariosMateriais = document.querySelectorAll(
        ".materials-modal form"
    );

    formulariosMateriais.forEach(function (formulario) {

        formulario.addEventListener("submit", function (event) {

            if (formulario.dataset.enviando === "true") {
                event.preventDefault();
                return;
            }

            formulario.dataset.enviando = "true";

            const botao = formulario.querySelector(
                'button[type="submit"]'
            );

            if (botao) {
                botao.disabled = true;
                botao.dataset.textoOriginal = botao.innerHTML;

                botao.innerHTML =
                    '<span class="spinner-border spinner-border-sm me-2" role="status"></span>' +
                    'Processando...';
            }

        });

    });

    // Garante que os percentuais selecionáveis sejam múltiplos de 10.
    const camposPercentuais = document.querySelectorAll(
        'select[name="percentual_aberto"], ' +
        'select[name="percentual_consumido"]'
    );

    camposPercentuais.forEach(function (campo) {

        campo.addEventListener("change", function () {

            const valor = Number(campo.value);

            if (!Number.isInteger(valor) || valor < 0 ||
                valor > 100 || valor % 10 !== 0) {

                campo.value = "";
                alert("Selecione um percentual de 10 em 10%.");

            }

        });

    });

});

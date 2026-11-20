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

            const percentualValido = Number.isInteger(valor) &&
                valor >= 0 && valor <= 100 && valor % 10 === 0;

            let feedback = campo.parentElement.querySelector(
                ".invalid-feedback[data-percentual-feedback]"
            );

            if (!percentualValido) {
                campo.value = "";
                campo.classList.add("is-invalid");

                if (!feedback) {
                    feedback = document.createElement("div");
                    feedback.className = "invalid-feedback";
                    feedback.dataset.percentualFeedback = "true";
                    feedback.textContent = "Selecione um percentual de 10 em 10%.";
                    campo.insertAdjacentElement("afterend", feedback);
                }
            } else {
                campo.classList.remove("is-invalid");
                if (feedback) feedback.remove();
            }

        });

    });

});


/* =====================================================
   TASKBERRY | MODAL DE CONFIRMAÇÃO REUTILIZÁVEL
   Todas as confirmações usam o modal visual padrão.
===================================================== */

document.addEventListener("DOMContentLoaded", function () {
    const modalElement = document.getElementById("taskberryConfirmModal");
    if (!modalElement || !window.bootstrap) return;

    const modal = bootstrap.Modal.getOrCreateInstance(modalElement, {
        backdrop: "static",
        keyboard: true
    });

    const kicker = modalElement.querySelector("[data-confirm-kicker]");
    const title = modalElement.querySelector("[data-confirm-title-text]");
    const message = modalElement.querySelector("[data-confirm-message]");
    const confirmButton = modalElement.querySelector("[data-confirm-submit]");
    const icon = modalElement.querySelector("[data-confirm-icon]");
    const dangerIcon = modalElement.querySelector("[data-confirm-danger-icon]");
    const neutralIcon = modalElement.querySelector("[data-confirm-neutral-icon]");
    const passwordWrap = modalElement.querySelector("[data-confirm-password-wrap]");
    const passwordInput = modalElement.querySelector("#taskberryDeletePassword");

    let pendingForm = null;
    let pendingResolver = null;
    let approvedForm = null;

    function safeIconClass(value) {
        const iconName = String(value || "bi-exclamation-circle");
        return /^bi-[a-z0-9-]+$/.test(iconName) ? iconName : "bi-exclamation-circle";
    }

    function openConfirmation(options = {}) {
        if (pendingResolver) {
            pendingResolver(false);
            pendingResolver = null;
        }

        const variant = options.variant === "primary" ? "primary" : "danger";

        if (kicker) kicker.textContent = options.kicker || "CONFIRMAÇÃO DE OPERAÇÃO";
        if (title) title.textContent = options.title || "Confirmar operação";
        if (message) message.textContent = options.message || "Deseja realmente continuar?";

        if (confirmButton) {
            confirmButton.textContent = options.confirmText || "Confirmar";
            confirmButton.classList.toggle("employee-danger-button", variant === "danger");
            confirmButton.classList.toggle("employee-primary-button", variant === "primary");
        }

        if (icon) icon.className = "bi " + safeIconClass(options.icon);
        if (dangerIcon) dangerIcon.classList.toggle("d-none", variant !== "danger");
        if (neutralIcon) neutralIcon.classList.toggle("d-none", variant !== "primary");
        if (passwordWrap) passwordWrap.classList.toggle("d-none", options.requirePassword !== true);

        if (passwordInput) {
            passwordInput.value = "";
            passwordInput.classList.remove("is-invalid");
        }

        modal.show();

        return new Promise(resolve => {
            pendingResolver = resolve;
        });
    }

    window.TaskBerryConfirm = {
        ask: function (options) {
            pendingForm = null;
            return openConfirmation(options || {});
        }
    };

    document.addEventListener("submit", function (event) {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;

        const actionPath = new URL(form.action, window.location.href).pathname;
        const isPermanentDelete = /\/excluir-permanentemente(?:\/|$)/i.test(actionPath);

        if (!form.hasAttribute("data-confirm") && !isPermanentDelete) return;

        if (approvedForm === form || form.dataset.confirmApproved === "true") {
            form.dataset.confirmApproved = "false";
            approvedForm = null;
            return;
        }

        event.preventDefault();
        pendingForm = form;

        const requirePassword =
            document.body.dataset.requireDeletePassword === "true" &&
            isPermanentDelete;

        openConfirmation({
            kicker: form.dataset.confirmKicker || (isPermanentDelete ? "EXCLUSÃO DEFINITIVA" : undefined),
            title: form.dataset.confirmTitle || (isPermanentDelete ? "Excluir permanentemente" : undefined),
            message: form.dataset.confirm || (isPermanentDelete
                ? "Esta ação não poderá ser desfeita. Deseja realmente excluir este registro?"
                : "Deseja realmente continuar?"),
            confirmText: form.dataset.confirmButton || (isPermanentDelete ? "Excluir definitivamente" : "Confirmar"),
            icon: form.dataset.confirmIcon || (isPermanentDelete ? "bi-trash3" : "bi-exclamation-circle"),
            variant: form.dataset.confirmVariant || "danger",
            requirePassword: requirePassword
        });
    }, true);

    confirmButton.addEventListener("click", function () {
        const form = pendingForm;
        const resolver = pendingResolver;

        if (form && form.isConnected && passwordWrap && !passwordWrap.classList.contains("d-none")) {
            const senha = passwordInput ? passwordInput.value.trim() : "";

            if (!senha) {
                passwordInput?.classList.add("is-invalid");
                passwordInput?.focus();
                return;
            }

            let hiddenPassword = form.querySelector('input[name="senha_confirmacao"]');
            if (!hiddenPassword) {
                hiddenPassword = document.createElement("input");
                hiddenPassword.type = "hidden";
                hiddenPassword.name = "senha_confirmacao";
                form.appendChild(hiddenPassword);
            }
            hiddenPassword.value = senha;
        }

        pendingForm = null;
        pendingResolver = null;

        if (resolver) resolver(true);

        if (form && form.isConnected) {
            approvedForm = form;
            form.dataset.confirmApproved = "true";

            if (typeof form.requestSubmit === "function") {
                form.requestSubmit();
            } else {
                form.submit();
            }
        }

        modal.hide();
    });

    passwordInput?.addEventListener("input", function () {
        passwordInput.classList.remove("is-invalid");
    });

    modalElement.addEventListener("shown.bs.modal", function () {
        if (passwordWrap && !passwordWrap.classList.contains("d-none")) {
            passwordInput?.focus();
        }
    });

    modalElement.addEventListener("hidden.bs.modal", function () {
        if (pendingResolver) {
            pendingResolver(false);
            pendingResolver = null;
        }
        pendingForm = null;
        if (passwordInput) passwordInput.value = "";
    });
});


/* =====================================================
   TASKBERRY | SWITCHES DE PREFERÊNCIAS COM CONFIRMAÇÃO
===================================================== */
document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-setting-switch-input]").forEach(function (input) {
        const form = input.closest("form[data-setting-switch]");
        if (!form) return;
        const valor = form.querySelector("[data-switch-value]");
        const estadoInicial = input.checked;
        input.addEventListener("change", async function () {
            const novoEstado = input.checked;
            input.disabled = true;
            const confirmar = window.TaskBerryConfirm
                ? await window.TaskBerryConfirm.ask({
                    title: input.dataset.confirmTitle || "Confirmar alteração?",
                    message: input.dataset.confirmMessage || "Deseja realmente alterar esta preferência?",
                    confirmText: "Sim, alterar",
                    icon: "bi-sliders",
                    variant: "primary"
                })
                : false;
            if (!confirmar) {
                input.checked = !novoEstado;
                input.disabled = false;
                return;
            }
            if (valor) valor.value = novoEstado ? "true" : "false";
            form.submit();
        });
    });
});

/* =====================================================
   TASKBERRY | MENSAGENS TEMPORÁRIAS E VOLTAR AO TOPO
===================================================== */
document.addEventListener("DOMContentLoaded", function () {
    // Mensagens flash desaparecem após 5 segundos.
    document.querySelectorAll(".alert.alert-dismissible").forEach(function (alerta) {
        const tempo = Number(alerta.dataset.autoDismiss) || 5000;
        window.setTimeout(function () {
            if (!alerta.isConnected) return;
            if (window.bootstrap && bootstrap.Alert) {
                bootstrap.Alert.getOrCreateInstance(alerta).close();
            } else {
                alerta.classList.add("fade");
                window.setTimeout(() => alerta.remove(), 250);
            }
        }, tempo);
    });

    // Botão global de retorno ao topo. O botão fica no index.html.
    const botaoTopo = document.getElementById("taskberryBackToTop");
    if (botaoTopo) {
        const atualizarVisibilidade = function () {
            botaoTopo.classList.toggle("is-visible", window.scrollY > 350);
        };

        atualizarVisibilidade();
        window.addEventListener("scroll", atualizarVisibilidade, { passive: true });

        botaoTopo.addEventListener("click", function () {
            window.scrollTo({ top: 0, behavior: "smooth" });
        });
    }
});

/* =====================================================
   TASKBERRY | PRESERVAR POSIÇÃO DA PÁGINA
   Mantém a rolagem após formulários e filtros que retornam
   à mesma tela. Não interfere em navegações para outras telas.
===================================================== */
(function () {
    const storageKey = "taskberry:scroll-position";

    function salvarPosicao() {
        try {
            sessionStorage.setItem(storageKey, JSON.stringify({
                path: window.location.pathname,
                y: window.scrollY,
                savedAt: Date.now()
            }));
        } catch (error) {
            // A navegação continua normalmente se o armazenamento estiver indisponível.
        }
    }

    document.addEventListener("submit", function (event) {
        const formulario = event.target;
        if (!(formulario instanceof HTMLFormElement)) return;
        if (formulario.target && formulario.target !== "_self") return;
        salvarPosicao();
    }, true);

    document.addEventListener("click", function (event) {
        const elemento = event.target instanceof Element
            ? event.target
            : event.target.parentElement;
        const link = elemento ? elemento.closest("a[href]") : null;
        if (!link || event.defaultPrevented) return;
        if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        if (link.target && link.target !== "_self") return;

        const destino = new URL(link.href, window.location.href);
        if (destino.origin !== window.location.origin) return;
        if (destino.pathname !== window.location.pathname) return;
        if (destino.hash && destino.hash !== window.location.hash) return;

        salvarPosicao();
    }, true);

    window.addEventListener("pageshow", function () {
        let estado = null;

        try {
            estado = JSON.parse(sessionStorage.getItem(storageKey) || "null");
            sessionStorage.removeItem(storageKey);
        } catch (error) {
            return;
        }

        if (!estado || estado.path !== window.location.pathname) return;
        if (Date.now() - Number(estado.savedAt || 0) > 60000) return;

        requestAnimationFrame(function () {
            requestAnimationFrame(function () {
                window.scrollTo({
                    top: Math.max(0, Number(estado.y) || 0),
                    left: 0,
                    behavior: "auto"
                });
            });
        });
    });
})();

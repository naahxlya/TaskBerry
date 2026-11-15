from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    current_app
)

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from werkzeug.security import check_password_hash

from app.database.connection import get_database


perfil_bp = Blueprint("perfil", __name__)


# ==========================================
# VISUALIZAR E EDITAR PERFIL
# ==========================================

@perfil_bp.route("/perfil", methods=["GET", "POST"])
def meu_perfil():

    db = get_database()
    usuarios = db["usuarios"]

    usuario_id = session.get("usuario_id")

    usuario = usuarios.find_one({
        "_id": ObjectId(usuario_id)
    })

    if not usuario:
        session.clear()
        flash("Sua sessão não é mais válida. Entre novamente.", "warning")
        return redirect(url_for("inicio"))

    if request.method == "POST":

        nome = request.form.get("nome", "").strip()
        negocio = request.form.get("negocio", "").strip()
        email = request.form.get("email", "").strip().lower()
        telefone = request.form.get("telefone", "").strip()

        if not all([nome, negocio, email, telefone]):
            flash("Preencha todos os campos.", "danger")

        elif "@" not in email or "." not in email.split("@")[-1]:
            flash("Informe um e-mail válido.", "danger")

        else:
            try:
                usuarios.update_one(
                    {"_id": ObjectId(usuario_id)},
                    {
                        "$set": {
                            "nome": nome,
                            "negocio": negocio,
                            "email": email,
                            "telefone": telefone
                        }
                    }
                )

                # Atualiza os dados exibidos na sessão
                session["usuario_nome"] = nome
                session["usuario_email"] = email

                flash("Seus dados foram atualizados com sucesso!", "success")

                return redirect(url_for("perfil.meu_perfil"))

            except DuplicateKeyError:
                flash(
                    "Este e-mail já está sendo utilizado por outra conta.",
                    "warning"
                )

            except Exception:
                current_app.logger.exception("Erro ao atualizar perfil.")

                flash(
                    "Não foi possível atualizar seus dados.",
                    "danger"
                )

    usuario = usuarios.find_one({
        "_id": ObjectId(usuario_id)
    })

    return render_template(
        "perfil.html",
        usuario=usuario
    )


# ==========================================
# EXCLUIR CONTA
# ==========================================

@perfil_bp.route("/perfil/excluir", methods=["POST"])
def excluir_conta():

    usuario_id = session.get("usuario_id")

    frase_confirmacao = request.form.get(
        "confirmacao",
        ""
    ).strip()

    senha_atual = request.form.get("senha_atual", "")

    if frase_confirmacao != "EXCLUIR MINHA CONTA":
        flash("A confirmação digitada está incorreta.", "danger")
        return redirect(url_for("perfil.meu_perfil"))

    try:
        db = get_database()
        usuarios = db["usuarios"]

        usuario = usuarios.find_one({
            "_id": ObjectId(usuario_id)
        })

        if not usuario:
            session.clear()
            return redirect(url_for("inicio"))

        if not check_password_hash(usuario["senha"], senha_atual):
            flash("A senha atual está incorreta. A conta não foi excluída.", "danger")
            return redirect(url_for("perfil.meu_perfil"))

        usuarios.delete_one({
            "_id": ObjectId(usuario_id)
        })

        session.clear()

        flash(
            "Sua conta foi excluída com sucesso.",
            "success"
        )

        return redirect(url_for("inicio"))

    except Exception:
        current_app.logger.exception("Erro ao excluir conta.")

        flash(
            "Não foi possível excluir sua conta. Tente novamente.",
            "danger"
        )

        return redirect(url_for("perfil.meu_perfil"))
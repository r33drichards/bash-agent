from flask import Blueprint, render_template, current_app

main_bp = Blueprint('main', __name__)


@main_bp.route("/")
def index():
    title = current_app.config.get("TITLE", "Claude Code Agent")
    return render_template("index.html", title=title)
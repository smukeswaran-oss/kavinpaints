import re
import secrets
import sqlite3
import uuid
from datetime import datetime
from functools import wraps
from io import BytesIO
from pathlib import Path

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_file, session, url_for)
from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "cards.db"
ADMIN_USER = "kps"
ADMIN_PASSWORD = "kps@123"
UPLOAD_DIR = BASE_DIR / "uploads"
CARD_DIR = BASE_DIR / "cards"
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_NUMBER = 200

app = Flask(__name__)
app.secret_key = "gift-card-app-secret-key"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

UPLOAD_DIR.mkdir(exist_ok=True)
CARD_DIR.mkdir(exist_ok=True)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.context_processor
def inject_globals():
    return {"MAX_NUMBER": MAX_NUMBER}


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number INTEGER UNIQUE NOT NULL,
                name TEXT NOT NULL,
                mobile TEXT NOT NULL,
                site TEXT NOT NULL,
                location TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                photo TEXT NOT NULL,
                card_image TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(cards)")}
        if "email" in cols:
            conn.execute("ALTER TABLE cards DROP COLUMN email")
        if "amount" not in cols:
            conn.execute("ALTER TABLE cards ADD COLUMN amount REAL NOT NULL DEFAULT 0")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bill_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                photo TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (card_id) REFERENCES cards(id) ON DELETE CASCADE
            )
            """
        )


def next_number(db):
    used = {row["number"] for row in db.execute("SELECT number FROM cards")}
    for n in range(1, MAX_NUMBER + 1):
        if n not in used:
            return n
    return None


def load_font(size, bold=False):
    candidates = ["arialbd.ttf", "ariblk.ttf"] if bold else ["arial.ttf"]
    if not bold:
        candidates = ["arial.ttf"]
    for name in candidates:
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def center_text(draw, cx, cy, text, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    x = cx - (bbox[2] - bbox[0]) / 2 - bbox[0]
    y = cy - (bbox[3] - bbox[1]) / 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=fill)


def fit_font(draw, text, max_width, font_size, bold=False, min_size=18):
    size = font_size
    while size > min_size:
        font = load_font(size, bold)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 2
    return load_font(min_size, bold)


def make_card_image(number, name, site, location, amount, out_path):
    w, h = 1000, 620
    img = Image.new("RGBA", (w, h), (14, 34, 58, 255))
    draw = ImageDraw.Draw(img, "RGBA")

    for y in range(h):
        t = y / h
        r = int(16 + (6 + 16) * t)
        g = int(44 + (18 + 44) * t)
        b = int(76 + (30 + 76) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b, 255))

    draw.ellipse([-160, -160, 260, 260], fill=(255, 255, 255, 14))
    draw.ellipse([820, 440, 1180, 800], fill=(255, 255, 255, 12))
    draw.ellipse([760, -120, 1020, 140], fill=(212, 175, 55, 30))

    draw.rectangle([20, 20, w - 21, h - 21], outline=(212, 175, 55, 255), width=4)
    draw.rectangle([32, 32, w - 33, h - 33], outline=(212, 175, 55, 90), width=2)

    title_font = fit_font(draw, site, 900, 42, bold=True)
    center_text(draw, w / 2, 70, site.strip(), title_font, (232, 196, 100, 255))

    sub_font = load_font(22)
    center_text(draw, w / 2, 124, f"Lucky Number Series 1 - {MAX_NUMBER}", sub_font, (170, 190, 214, 255))

    circle_c = (275, 370)
    radius = 158
    draw.ellipse(
        [circle_c[0] - radius - 12, circle_c[1] - radius - 12,
         circle_c[0] + radius + 12, circle_c[1] + radius + 12],
        outline=(212, 175, 55, 160), width=3,
    )
    draw.ellipse(
        [circle_c[0] - radius, circle_c[1] - radius,
         circle_c[0] + radius, circle_c[1] + radius],
        fill=(212, 175, 55, 255),
    )
    draw.ellipse(
        [circle_c[0] - radius + 14, circle_c[1] - radius + 14,
         circle_c[0] + radius - 14, circle_c[1] + radius - 14],
        outline=(14, 34, 58, 120), width=3,
    )

    num_font = load_font(150, bold=True)
    center_text(draw, circle_c[0], circle_c[1] - 12, str(number), num_font, (14, 34, 58, 255))
    of_font = load_font(24, bold=True)
    center_text(draw, circle_c[0], circle_c[1] + 92, f"OF {MAX_NUMBER}", of_font, (14, 34, 58, 200))

    name_font = fit_font(draw, name, 450, 52, bold=True)
    draw.text((490, 250), name.strip(), font=name_font, fill=(255, 255, 255, 255))

    site_line = f"Site: {site}"
    loc_line = f"Location: {location}"
    site_font = fit_font(draw, site_line, 450, 26)
    loc_font = fit_font(draw, loc_line, 450, 26)
    draw.text((492, 326), site_line, font=site_font, fill=(186, 205, 226, 255))
    draw.text((492, 362), loc_line, font=loc_font, fill=(186, 205, 226, 255))

    amount_line = f"Amount: Rs. {amount:,.0f}"
    amount_font = fit_font(draw, amount_line, 450, 30, bold=True)
    draw.text((492, 398), amount_line, font=amount_font, fill=(232, 196, 100, 255))

    draw.line([(492, 448), (930, 448)], fill=(212, 175, 55, 140), width=2)
    foot_font = load_font(22)
    draw.text((492, 462), "Show this card to claim your gift", font=foot_font, fill=(212, 175, 55, 230))
    draw.text((492, 498), f"Card No. {number:03d}", font=foot_font, fill=(150, 170, 196, 255))

    img.convert("RGB").save(out_path, "PNG")
    return out_path


def ensure_card_image(rec):
    """Restore the derived card image when it is missing from disk."""
    path = BASE_DIR / rec["card_image"]
    if not path.exists():
        make_card_image(
            rec["number"], rec["name"], rec["site"], rec["location"],
            rec["amount"], path,
        )
    return path


def build_pdf(rec, db=None):
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    margin = 12

    def place_image(pdf_obj, path):
        try:
            with Image.open(path) as im:
                ratio = im.width / im.height
            max_w = pdf_obj.w - margin * 2
            max_h = pdf_obj.h - margin * 2
            w = max_w
            h = w / ratio
            if h > max_h:
                h = max_h
                w = h * ratio
            pdf_obj.image(str(path), x=(pdf_obj.w - w) / 2, y=(pdf_obj.h - h) / 2, w=w, h=h)
        except Exception:
            pass

    pdf.add_page()
    place_image(pdf, ensure_card_image(rec))

    if db is not None:
        entries = db.execute(
            "SELECT photo FROM bill_entries WHERE card_id = ? ORDER BY id", (rec["id"],)
        ).fetchall()
        for e in entries:
            if e["photo"]:
                p = BASE_DIR / e["photo"]
                if p.exists():
                    pdf.add_page()
                    place_image(pdf, p)
    else:
        photo = BASE_DIR / rec["photo"]
        if photo.exists():
            pdf.add_page()
            place_image(pdf, photo)

    return bytes(pdf.output())


@app.route("/", methods=["GET", "POST"])
def index():
    rec = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        mobile = re.sub(r"\D", "", request.form.get("mobile", "").strip())[:10]
        site = request.form.get("site", "").strip() or "Kavinesh Paint Shop"
        location = request.form.get("location", "").strip()
        amount_raw = request.form.get("amount", "").strip()
        photo = request.files.get("photo")

        errors = []
        amount = 0.0
        if not name:
            errors.append("Name is required.")
        if len(mobile) != 10:
            errors.append("Mobile number must be exactly 10 digits.")
        if not site:
            errors.append("Site name is required.")
        if not location:
            errors.append("Location is required.")
        if amount_raw:
            try:
                amount = float(amount_raw)
                if amount < 0:
                    errors.append("Amount must be a positive number.")
            except ValueError:
                errors.append("Enter a valid amount.")
        if photo is None or photo.filename == "":
            errors.append("Bill photo is required.")
        elif Path(secure_filename(photo.filename)).suffix.lower() not in ALLOWED_EXT:
            errors.append("Bill photo must be JPG, PNG or WEBP.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("index.html", rec=None, form=request.form)

        db = get_db()
        # Strictly one card per mobile number!
        existing = db.execute(
            "SELECT * FROM cards WHERE trim(mobile) = ? ORDER BY id ASC",
            (mobile,),
        ).fetchone()

        ext = Path(secure_filename(photo.filename)).suffix.lower() or ".jpg"
        now = datetime.now().isoformat(timespec="seconds")

        if existing is not None:
            photo_name = f"{uuid.uuid4().hex}{ext}"
            photo.save(UPLOAD_DIR / photo_name)

            new_total = (existing["amount"] or 0) + (amount if amount > 0 else 0)
            db.execute(
                """UPDATE cards 
                   SET amount = ?, photo = ?, location = COALESCE(NULLIF(?, ''), location)
                   WHERE id = ?""",
                (new_total, f"uploads/{photo_name}", location, existing["id"]),
            )
            db.execute(
                """INSERT INTO bill_entries (card_id, amount, photo, created_at)
                   VALUES (?, ?, ?, ?)""",
                (existing["id"], amount, f"uploads/{photo_name}", now),
            )
            db.commit()

            card_path = CARD_DIR / f"card_{existing['number']:03d}.png"
            make_card_image(existing["number"], existing["name"], existing["site"],
                            location or existing["location"], new_total, card_path)

            rec = db.execute("SELECT * FROM cards WHERE id = ?", (existing["id"],)).fetchone()
            if amount > 0:
                flash(
                    f"Mobile {mobile} is assigned Card #{existing['number']}. "
                    f"New bill of ₹{amount:,.2f} added. Total bill amount: ₹{new_total:,.2f}.",
                    "success",
                )
            else:
                flash(
                    f"Mobile {mobile} is assigned Card #{existing['number']}. "
                    f"New bill photo saved successfully (Total bill: ₹{new_total:,.2f}).",
                    "success",
                )
            return render_template("index.html", rec=rec, form=request.form)

        number = next_number(db)
        if number is None:
            flash(f"All {MAX_NUMBER} gift card numbers are already issued.", "error")
            return render_template("index.html", rec=None, form=request.form)

        photo_name = f"{uuid.uuid4().hex}{ext}"
        photo_path = UPLOAD_DIR / photo_name
        photo.save(photo_path)

        card_name = f"card_{number:03d}.png"
        card_path = CARD_DIR / card_name
        make_card_image(number, name, site, location, amount, card_path)

        cur = db.execute(
            """INSERT INTO cards (number, name, mobile, site, location, amount,
                                  photo, card_image, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (number, name, mobile, site, location, amount,
             f"uploads/{photo_name}", f"cards/{card_name}", now),
        )
        db.execute(
            """INSERT INTO bill_entries (card_id, amount, photo, created_at)
               VALUES (?, ?, ?, ?)""",
            (cur.lastrowid, amount, f"uploads/{photo_name}", now),
        )
        db.commit()
        rec = db.execute("SELECT * FROM cards WHERE id = ?", (cur.lastrowid,)).fetchone()
        flash(f"Success! Your gift card number is {number}.", "success")

    return render_template("index.html", rec=rec, form=request.form if request.method == "POST" else {})


@app.route("/gift-card", methods=["GET", "POST"])
def gift_card():
    rec = None
    if request.method == "POST":
        mobile = re.sub(r"\D", "", request.form.get("mobile", "").strip())[:10]
        if not mobile:
            flash("Please enter your 10-digit mobile number.", "error")
        elif len(mobile) != 10:
            flash("Mobile number must be exactly 10 digits.", "error")
        else:
            db = get_db()
            rec = db.execute(
                "SELECT * FROM cards WHERE trim(mobile) = ? ORDER BY id ASC",
                (mobile,),
            ).fetchone()
            if rec is None:
                flash("No gift card found for that mobile number.", "error")
    return render_template("gift.html", rec=rec, form=request.form if request.method == "POST" else {})


@app.route("/admin/record/<int:rec_id>")
@admin_required
def admin_record(rec_id):
    db = get_db()
    rec = db.execute("SELECT * FROM cards WHERE id = ?", (rec_id,)).fetchone()
    if rec is None:
        abort(404)
    entries = db.execute(
        "SELECT * FROM bill_entries WHERE card_id = ? ORDER BY id", (rec_id,)
    ).fetchall()
    return render_template("record.html", rec=rec, entries=entries)


@app.route("/admin/edit/<int:rec_id>", methods=["GET", "POST"])
@admin_required
def admin_edit(rec_id):
    db = get_db()
    rec = db.execute("SELECT * FROM cards WHERE id = ?", (rec_id,)).fetchone()
    if rec is None:
        abort(404)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        mobile = re.sub(r"\D", "", request.form.get("mobile", "").strip())[:10]
        site = request.form.get("site", "").strip() or rec["site"] or "Kavinesh Paint Shop"
        location = request.form.get("location", "").strip()
        amount_raw = request.form.get("amount", "").strip()

        errors = []
        amount = rec["amount"]
        if not name:
            errors.append("Name is required.")
        if len(mobile) != 10:
            errors.append("Mobile number must be exactly 10 digits.")
        else:
            dup = db.execute(
                "SELECT id, number FROM cards WHERE trim(mobile) = ? AND id != ?",
                (mobile, rec_id),
            ).fetchone()
            if dup:
                errors.append(f"Mobile number {mobile} is already assigned to Card #{dup['number']}.")
        if not site:
            errors.append("Site name is required.")
        if not location:
            errors.append("Location is required.")
        if amount_raw:
            try:
                amount = float(amount_raw)
                if amount < 0:
                    errors.append("Amount must be a positive number.")
            except ValueError:
                errors.append("Enter a valid amount.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("edit.html", rec=rec, form=request.form)

        db.execute(
            """UPDATE cards SET name = ?, mobile = ?, site = ?, location = ?, amount = ?
               WHERE id = ?""",
            (name, mobile, site, location, amount, rec_id),
        )
        db.commit()

        card_path = CARD_DIR / f"card_{rec['number']:03d}.png"
        make_card_image(rec["number"], name, site, location, amount, card_path)

        flash(f"Record #{rec['number']} updated successfully.", "success")
        return redirect(url_for("admin"))

    return render_template("edit.html", rec=rec, form={})


@app.route("/admin/delete/<int:rec_id>", methods=["POST"])
@admin_required
def admin_delete(rec_id):
    db = get_db()
    rec = db.execute("SELECT * FROM cards WHERE id = ?", (rec_id,)).fetchone()
    if rec is None:
        abort(404)

    photo_path = BASE_DIR / rec["photo"]
    card_path = BASE_DIR / rec["card_image"]
    for p in (photo_path, card_path):
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass

    db.execute("DELETE FROM cards WHERE id = ?", (rec_id,))
    db.commit()
    flash(f"Record #{rec['number']} deleted.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/photo/<int:rec_id>")
@admin_required
def admin_photo(rec_id):
    rec = get_db().execute("SELECT * FROM cards WHERE id = ?", (rec_id,)).fetchone()
    if rec is None:
        abort(404)
    path = BASE_DIR / rec["photo"]
    if not path.exists():
        abort(404)
    return send_file(path)


@app.route("/admin/entry-photo/<int:entry_id>")
@admin_required
def admin_entry_photo(entry_id):
    entry = get_db().execute("SELECT * FROM bill_entries WHERE id = ?", (entry_id,)).fetchone()
    if entry is None or not entry["photo"]:
        abort(404)
    path = BASE_DIR / entry["photo"]
    if not path.exists():
        abort(404)
    return send_file(path)


@app.route("/card/<int:rec_id>")
def card_image(rec_id):
    rec = get_db().execute("SELECT * FROM cards WHERE id = ?", (rec_id,)).fetchone()
    if rec is None:
        abort(404)
    return send_file(ensure_card_image(rec), mimetype="image/png")


@app.route("/download/<int:rec_id>")
def download(rec_id):
    db = get_db()
    rec = db.execute("SELECT * FROM cards WHERE id = ?", (rec_id,)).fetchone()
    if rec is None:
        abort(404)
    pdf_bytes = build_pdf(rec, db=db)
    return send_file(
        BytesIO(pdf_bytes),
        as_attachment=True,
        download_name=f"gift_card_{rec['number']:03d}_{rec['name'].replace(' ', '_')}.pdf",
        mimetype="application/pdf",
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if (secrets.compare_digest(username, ADMIN_USER)
                and secrets.compare_digest(password, ADMIN_PASSWORD)):
            session["admin_logged_in"] = True
            flash("Logged in successfully.", "success")
            nxt = request.args.get("next") or url_for("admin")
            if not nxt.startswith("/"):
                nxt = url_for("admin")
            return redirect(nxt)
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    flash("Logged out.", "success")
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin():
    db = get_db()
    q = request.args.get("q", "").strip()
    if q:
        rows = db.execute(
            """SELECT * FROM cards
               WHERE name LIKE ? OR mobile LIKE ? OR site LIKE ?
                     OR location LIKE ? OR number LIKE ?
               ORDER BY number""",
            tuple([f"%{q}%"] * 5),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM cards ORDER BY number").fetchall()

    total = db.execute("SELECT COUNT(*) AS c FROM cards").fetchone()["c"]
    number_map = {r["number"]: r["id"] for r in db.execute("SELECT number, id FROM cards")}

    bill_data = {}
    for r in rows:
        entries = db.execute(
            "SELECT amount, created_at FROM bill_entries WHERE card_id = ? ORDER BY id", (r["id"],)
        ).fetchall()
        amts = [e["amount"] for e in entries]
        if len(amts) >= 2:
            old_amount = sum(amts[:-1])
            new_amount = amts[-1]
        elif len(amts) == 1:
            old_amount = 0.0
            new_amount = amts[0]
        else:
            old_amount = r["amount"]
            new_amount = r["amount"]
        bill_data[r["id"]] = {
            "count": len(entries),
            "entries": [{"amount": e["amount"], "date": e["created_at"]} for e in entries],
            "total": r["amount"],
            "old": old_amount,
            "new": new_amount,
        }

    free = MAX_NUMBER - total
    stats = {
        "total": total,
        "free": free,
        "search_count": len(rows),
    }
    return render_template("admin.html", rows=rows, stats=stats, q=q,
                           number_map=number_map, bill_data=bill_data, amounts=bill_data)


init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

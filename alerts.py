"""Shared alert builder/dispatcher for the CLI ML app and browser app."""
import csv, datetime, os, threading, requests
LABEL = {"push_fall": "PUSH + FALL", "fall": "FALL"}

def load_env(path=".env"):
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))

def _valid_phone(n):
    return bool(n) and "X" not in n.upper()

def _norm(n):
    d = "".join(c for c in n if c.isdigit())
    return d[-10:]

def build(event, ctx, cfg, stn, stage="ALERT"):
    label = LABEL.get(event, event.upper())
    people = int(ctx.get("person_count", 1))
    people_text = f"{people} detected person" + ("" if people == 1 else "s")
    t = ctx["time"].strftime("%d-%b-%Y %H:%M:%S")
    maps = f"https://maps.google.com/?q={ctx['lat']:.6f},{ctx['lon']:.6f}"
    accuracy = f" GPS accuracy: +/-{ctx['accuracy']:.0f} m." if ctx.get("accuracy") is not None else ""
    near = f"Nearest station: {stn['name']} ({ctx['km']:.1f} km). Between {ctx['prev']} and {ctx['next']}."
    if stage == "HALTED":
        base = (f"RAILGUARD 360 UPDATE: Train {cfg['train']['number']} has HALTED after a {label} event involving {people_text}. "
                f"Location {ctx['lat']:.6f},{ctx['lon']:.6f} at {t}.{accuracy} Map: {maps}.")
    else:
        base = (f"RAILGUARD 360 ALERT: {label} event involving {people_text} from running train {cfg['train']['number']}, "
                f"coach {cfg['train']['coach']}, at {t}. Train speed {ctx['speed']:.0f} km/h. "
                f"Location {ctx['lat']:.6f},{ctx['lon']:.6f}.{accuracy} Map: {maps}.")
    c = cfg["contacts"]
    if stage == "HALTED":
        msg = {r: base + f" {near} Send emergency response/search team to the track location."
               for r in ("guard", "control", "police", "ambulance")}
    else:
        msg = {
            "guard": base + f" {near} Apply alarm chain / stop train safely and note the km point.",
            "control": base + f" {near} Guard and station police informed.",
            "police": base + f" {near} Send RPF/GRP search party to the track near this location. Train guard: {c['guard']['phone']}.",
            "ambulance": base + f" {near} Passenger may be injured beside the track. Please dispatch ambulance and medical team."
        }
    phone = {
        "guard": c["guard"]["phone"], "control": c["control"]["phone"],
        "police": stn.get("police_phone") or c["police"]["phone"],
        "ambulance": stn.get("ambulance_phone") or c["ambulance"]["phone"]
    }
    return {r: (phone[r], msg[r]) for r in msg}

def _send_fast2sms(numbers, text):
    key = os.environ.get("FAST2SMS_API_KEY", "")
    if not key: return None
    try:
        # flash=1 delivers a priority Flash/Class-0 SMS that pops up directly on phone screen without needing to open any file or app
        r = requests.post("https://www.fast2sms.com/dev/bulkV2", headers={"authorization": key},
                          data={"route":"q","message":text,"language":"english","flash":1,
                                "numbers":",".join(_norm(n) for n in numbers)}, timeout=20)
        return r.status_code == 200 and r.json().get("return") is True, f"Fast2SMS HTTP {r.status_code}"
    except Exception as e:
        return False, f"Fast2SMS {type(e).__name__}: {e}"

def _send_twilio(number, text):
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    tok = os.environ.get("TWILIO_AUTH_TOKEN", "")
    frm = os.environ.get("TWILIO_FROM_NUMBER") or os.environ.get("TWILIO_FROM", "")
    if not (sid and tok and frm): return None
    try:
        from twilio.rest import Client
        Client(sid, tok).messages.create(to=number, from_=frm, body=text)
        return True, "Twilio sent"
    except Exception as e:
        return False, f"Twilio {type(e).__name__}: {e}"

def _send_email(to_email, subject, text):
    user = os.environ.get("ALERT_EMAIL_USER", "terrorx2024@gmail.com")
    pwd = os.environ.get("ALERT_EMAIL_PASS", "")
    if not (user and pwd and to_email): return None
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        msg = MIMEMultipart()
        msg['From'] = f"RailGuard 360 Emergency <{user}>"
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(text, 'plain'))
        
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(user, pwd)
            server.sendmail(user, [to_email], msg.as_string())
        return True, "Email sent via Gmail"
    except Exception as e:
        return False, f"Email Error: {e}"

def send_all(messages, log="logs/alerts_log.csv"):
    load_env()
    os.makedirs(os.path.dirname(log) or ".", exist_ok=True)
    fast_key = bool(os.environ.get("FAST2SMS_API_KEY"))
    email_user = os.environ.get("ALERT_EMAIL_USER", "terrorx2024@gmail.com")
    email_pass = os.environ.get("ALERT_EMAIL_PASS", "")
    out = []
    
    # Process SMS
    if fast_key:
        valid = [to for to, _ in messages.values() if _valid_phone(to)]
        result = _send_fast2sms(valid, messages[next(iter(messages))][1]) if valid else None
        for role, (to, body) in messages.items():
            status = "SENT" if result and result[0] and _valid_phone(to) else ("NOT_SENT_placeholder_number" if not _valid_phone(to) else (result[1] if result else "DRY_RUN_no_sms_gateway"))
            out.append((role, to, status, body))
    else:
        for role, (to, body) in messages.items():
            if not _valid_phone(to): status = "NOT_SENT_placeholder_number"
            else:
                r = _send_twilio(to, body)
                status = "SENT" if r and r[0] else (r[1] if r else "DRY_RUN_no_sms_gateway")
            out.append((role, to, status, body))

    # Process Email if configured
    if email_pass:
        first_body = messages[next(iter(messages))][1]
        email_recipients = os.environ.get("ALERT_EMAIL_TO", "terrorx2024@gmail.com").split(",")
        for r_email in email_recipients:
            r_email = r_email.strip()
            if r_email:
                ok, err = _send_email(r_email, "🚨 EMERGENCY: RailGuard 360 Train Alert", first_body)
                out.append(("email_dispatch", r_email, "SENT" if ok else err, first_body))

    new = not os.path.exists(log)
    with open(log, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new: w.writerow(["time", "role", "to", "status", "message"])
        for role, to, status, body in out:
            w.writerow([datetime.datetime.now().isoformat(timespec="seconds"), role, to, status, body])
    return out

def dispatch(cfg, event, speed, loc, stations, stage="ALERT", log_path="logs/alerts_log.csv", on_done=None):
    """Web-compatible background dispatcher."""
    def work():
        near = stations[0]
        stn = {"name": near["name"], "police_phone":"", "ambulance_phone":""}
        ctx = dict(time=datetime.datetime.now(), lat=loc["lat"], lon=loc["lon"], speed=float(speed), km=float(loc.get("km", 0)),
                   prev=loc.get("segment", "").split(" -> ")[0], next=loc.get("segment", "").split(" -> ")[-1])
        rows = send_all(build(event, ctx, cfg, stn, stage), log_path)
        if on_done: on_done(rows)
    threading.Thread(target=work, daemon=True).start()

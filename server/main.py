"""Orbit Messenger - dependency-free Android/Termux starter using Python stdlib."""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import sqlite3, json, os, time, secrets, hashlib, re, smtplib, ssl, mimetypes
from email.parser import BytesParser
from email import policy
from email.message import EmailMessage

BASE=os.path.dirname(os.path.abspath(__file__))
# Load .env from the project folder (stdlib only; no extra package required).
def load_dotenv(path=os.path.join(BASE, ".env")):
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line=raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value=line.split("=", 1)
                key=key.strip(); value=value.strip()
                if len(value)>=2 and value[0]==value[-1] and value[0] in ("\"", "'"):
                    value=value[1:-1]
                os.environ.setdefault(key, value)
    except FileNotFoundError:
        pass
load_dotenv()
DB_PATH=os.environ.get('CHAT_DB', os.path.join(BASE,'orbit.db'))
COOKIE='orbit_session'

def connect():
    c=sqlite3.connect(DB_PATH, timeout=20)
    c.row_factory=sqlite3.Row
    return c

def init_db():
    with connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE, display_name TEXT NOT NULL, salt TEXT NOT NULL, passhash TEXT NOT NULL, created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS login_codes(user_id INTEGER PRIMARY KEY, code_hash TEXT NOT NULL, salt TEXT NOT NULL, expires INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, sent_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id INTEGER NOT NULL, recipient_id INTEGER NOT NULL, body TEXT NOT NULL, attachment_json TEXT, created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS uploads(filename TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, content_type TEXT NOT NULL, size INTEGER NOT NULL, created_at INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS messages_pair ON messages(sender_id,recipient_id,id);
        CREATE TABLE IF NOT EXISTS message_hidden(message_id INTEGER NOT NULL,user_id INTEGER NOT NULL,PRIMARY KEY(message_id,user_id));
        CREATE TABLE IF NOT EXISTS pinned_messages(message_id INTEGER NOT NULL,user_id INTEGER NOT NULL,PRIMARY KEY(message_id,user_id));
        CREATE TABLE IF NOT EXISTS chat_hidden(user_id INTEGER NOT NULL,other_id INTEGER NOT NULL,PRIMARY KEY(user_id,other_id));
        CREATE TABLE IF NOT EXISTS chat_pins(user_id INTEGER NOT NULL,other_id INTEGER NOT NULL,PRIMARY KEY(user_id,other_id));
        CREATE TABLE IF NOT EXISTS blocked_users(user_id INTEGER NOT NULL,other_id INTEGER NOT NULL,PRIMARY KEY(user_id,other_id));
        CREATE TABLE IF NOT EXISTS communities(id INTEGER PRIMARY KEY AUTOINCREMENT,owner_id INTEGER NOT NULL,name TEXT NOT NULL,kind TEXT NOT NULL,description TEXT DEFAULT '',created_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS community_members(community_id INTEGER NOT NULL,user_id INTEGER NOT NULL,role TEXT NOT NULL DEFAULT 'member',joined_at INTEGER NOT NULL,PRIMARY KEY(community_id,user_id));
        CREATE TABLE IF NOT EXISTS community_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,community_id INTEGER NOT NULL,sender_id INTEGER NOT NULL,body TEXT NOT NULL,attachment_json TEXT,created_at INTEGER NOT NULL);
        ''')
    # Upgrade existing Orbit databases without deleting accounts or messages.
    with connect() as c:
        cols={r['name'] for r in c.execute('PRAGMA table_info(users)').fetchall()}
        if 'email' not in cols: c.execute('ALTER TABLE users ADD COLUMN email TEXT')
        if 'avatar' not in cols: c.execute('ALTER TABLE users ADD COLUMN avatar TEXT')
        mcols={r['name'] for r in c.execute('PRAGMA table_info(messages)').fetchall()}
        if 'attachment_json' not in mcols: c.execute('ALTER TABLE messages ADD COLUMN attachment_json TEXT')
        if 'reply_to_id' not in mcols: c.execute('ALTER TABLE messages ADD COLUMN reply_to_id INTEGER')
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique ON users(email)')
init_db()

def c_user_exists(uid):
    with connect() as c: return bool(c.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone())

def pw_hash(pw,salt):
    return hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), bytes.fromhex(salt), 180000).hex()

def mask_email(email):
    try:
        name,domain=email.split('@',1); return (name[:1]+'***' if name else '***')+'@'+domain
    except Exception: return 'почту'

def send_login_code(email, code):
    host=os.environ.get('SMTP_HOST','').strip()
    user=os.environ.get('SMTP_USER','').strip()
    # Gmail app passwords are often displayed with spaces; remove separators.
    password=''.join(os.environ.get('SMTP_PASSWORD','').split())
    sender=os.environ.get('SMTP_FROM',user).strip()
    port=int(os.environ.get('SMTP_PORT','465'))
    if not all([host,user,password,sender]):
        raise RuntimeError('Почта не настроена: заполните SMTP_HOST, SMTP_USER, SMTP_PASSWORD и SMTP_FROM')
    msg=EmailMessage()
    msg['Subject']='Код входа в Orbit'
    msg['From']=sender
    msg['To']=email
    msg.set_content(f'Код входа в Orbit: {code}\n\nКод действует 5 минут. Если вы не запрашивали вход, проигнорируйте письмо.')
    context=ssl.create_default_context()

    # Port 465 uses implicit TLS; 587 uses STARTTLS. If 465 is unexpectedly
    # disconnected, retry once using 587. Authentication errors are not retried.
    attempts=[('ssl', port)]
    if port == 465:
        attempts.append(('starttls', 587))
    errors=[]
    for mode, attempt_port in attempts:
        smtp=None
        stage='connect'
        try:
            if mode == 'ssl':
                smtp=smtplib.SMTP_SSL(host, attempt_port, context=context, timeout=25)
            else:
                smtp=smtplib.SMTP(host, attempt_port, timeout=25)
                stage='starttls'
                smtp.ehlo()
                smtp.starttls(context=context)
            stage='ehlo'
            smtp.ehlo()
            stage='auth'
            smtp.login(user,password)
            stage='send'
            smtp.send_message(msg)
            try:
                smtp.quit()
            except smtplib.SMTPException:
                pass
            print(f'[SMTP] Email sent using {mode.upper()} port {attempt_port}', flush=True)
            return
        except smtplib.SMTPAuthenticationError as e:
            raise RuntimeError(f'SMTP authentication rejected by server (port {attempt_port}, code {e.smtp_code}). Check Gmail app password and account.') from e
        except Exception as e:
            errors.append(f'{mode.upper()}:{attempt_port} at {stage} -> {type(e).__name__}: {e}')
            print(f'[SMTP] Attempt {mode.upper()}:{attempt_port} failed at {stage}: {type(e).__name__}: {e}', flush=True)
        finally:
            if smtp is not None:
                try:
                    smtp.close()
                except Exception:
                    pass
    raise RuntimeError('SMTP attempts failed: ' + ' | '.join(errors))

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print('%s - %s' % (self.address_string(), fmt%args))
    def send_json(self, code, obj, extra_headers=None):
        data=json.dumps(obj,ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store')
        if extra_headers:
            for k,v in extra_headers: self.send_header(k,v)
        self.end_headers(); self.wfile.write(data)
    def read_json(self):
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n>20000: return None
            return json.loads(self.rfile.read(n) or b'{}')
        except Exception: return None
    def user(self):
        auth=self.headers.get('Authorization','')
        token=auth[7:].strip() if auth.lower().startswith('bearer ') else None
        if not token:
            raw=self.headers.get('Cookie','')
            for part in raw.split(';'):
                k,_,v=part.strip().partition('=')
                if k==COOKIE: token=v
        if not token:return None
        with connect() as c:
            s=c.execute('SELECT user_id FROM sessions WHERE token=? AND expires>?',(token,int(time.time()))).fetchone()
            if not s:return None
            return c.execute('SELECT id,username,email,display_name,avatar,created_at FROM users WHERE id=?',(s['user_id'],)).fetchone()
    def do_GET(self):
        p=urlparse(self.path)
        if p.path=='/' or p.path=='/index.html':
            try: data=open(os.path.join(BASE,'static','index.html'),'rb').read()
            except OSError: return self.send_json(500,{'detail':'Файл интерфейса не найден'})
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data); return
        if p.path.startswith('/uploads/'):
            viewer=self.user()
            if not viewer:return self.send_json(401,{'detail':'Войдите для просмотра файлов'})
            name=os.path.basename(p.path[len('/uploads/'):])
            with connect() as c:
                meta=c.execute('SELECT owner_id,content_type FROM uploads WHERE filename=?',(name,)).fetchone()
                allowed=bool(meta and meta['owner_id']==viewer['id'])
                if not allowed and meta:
                    allowed=bool(c.execute('SELECT 1 FROM messages WHERE attachment_json LIKE ? AND (sender_id=? OR recipient_id=?) LIMIT 1',('%'+name+'%',viewer['id'],viewer['id'])).fetchone())
                if not allowed and meta:
                    allowed=bool(c.execute('SELECT 1 FROM users WHERE avatar=?',(('/uploads/'+name),)).fetchone())
            if not meta:return self.send_json(404,{'detail':'Файл не найден'})
            if not allowed:return self.send_json(403,{'detail':'Нет доступа к файлу'})
            try: data=open(os.path.join(BASE,'uploads',name),'rb').read()
            except OSError:return self.send_json(404,{'detail':'Файл отсутствует'})
            self.send_response(200); self.send_header('Content-Type',meta['content_type']); self.send_header('Content-Length',str(len(data))); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(data); return
        if p.path=='/api/me':
            u=self.user(); return self.send_json(200,dict(u) if u else {'detail':'Не авторизован'}) if u else self.send_json(401,{'detail':'Не авторизован'})
        if p.path=='/api/users':
            u=self.user()
            if not u:return self.send_json(401,{'detail':'Войдите в аккаунт'})
            q=parse_qs(p.query).get('q',[''])[0].strip().lstrip('@')
            if len(q)<2:return self.send_json(200,{'users':[]})
            with connect() as c:
                rows=c.execute('SELECT id,username,display_name,avatar FROM users WHERE id=? OR username LIKE ? OR display_name LIKE ? LIMIT 25',(int(q) if q.isdigit() else -1,'%'+q+'%','%'+q+'%')).fetchall()
            return self.send_json(200,{'users':[dict(x) for x in rows if x['id']!=u['id']]})
        if p.path=='/api/chats':
            u=self.user()
            if not u:return self.send_json(401,{'detail':'Войдите в аккаунт'})
            with connect() as c:
                rows=c.execute('''SELECT other.id,other.username,other.display_name,other.avatar,
                    (SELECT m.body FROM messages m WHERE ((m.sender_id=? AND m.recipient_id=other.id) OR (m.sender_id=other.id AND m.recipient_id=?)) ORDER BY m.id DESC LIMIT 1) AS last_message,
                    (SELECT m.created_at FROM messages m WHERE ((m.sender_id=? AND m.recipient_id=other.id) OR (m.sender_id=other.id AND m.recipient_id=?)) ORDER BY m.id DESC LIMIT 1) AS last_time,
                    EXISTS(SELECT 1 FROM chat_pins cp WHERE cp.user_id=? AND cp.other_id=other.id) AS pinned,
                    EXISTS(SELECT 1 FROM blocked_users bu WHERE bu.user_id=? AND bu.other_id=other.id) AS blocked
                    FROM users other WHERE other.id IN (SELECT recipient_id FROM messages WHERE sender_id=? UNION SELECT sender_id FROM messages WHERE recipient_id=?)
                    AND NOT EXISTS(SELECT 1 FROM chat_hidden h WHERE h.user_id=? AND h.other_id=other.id)
                    ORDER BY pinned DESC,last_time DESC''',(u['id'],u['id'],u['id'],u['id'],u['id'],u['id'],u['id'],u['id'],u['id'])).fetchall()
            return self.send_json(200,{'chats':[dict(x) for x in rows]})
        if p.path=='/api/communities':
            u=self.user()
            if not u:return self.send_json(401,{'detail':'Войдите в аккаунт'})
            with connect() as c:
                rows=c.execute('''SELECT co.id,co.name,co.kind,co.description,co.owner_id,
                    (SELECT COUNT(*) FROM community_members cm WHERE cm.community_id=co.id) AS members
                    FROM communities co JOIN community_members cm ON cm.community_id=co.id
                    WHERE cm.user_id=? ORDER BY co.id DESC''',(u['id'],)).fetchall()
            return self.send_json(200,{'communities':[dict(x) for x in rows]})
        if p.path.startswith('/api/community-messages/'):
            u=self.user()
            if not u:return self.send_json(401,{'detail':'Войдите в аккаунт'})
            try: cid=int(p.path.rsplit('/',1)[-1])
            except ValueError:return self.send_json(400,{'detail':'ID сообщества некорректен'})
            with connect() as c:
                member=c.execute('SELECT role FROM community_members WHERE community_id=? AND user_id=?',(cid,u['id'])).fetchone()
                if not member:return self.send_json(403,{'detail':'Нет доступа к сообществу'})
                rows=c.execute('''SELECT cm.id,cm.sender_id,cm.body,cm.attachment_json,cm.created_at,u.display_name,u.username
                    FROM community_messages cm JOIN users u ON u.id=cm.sender_id WHERE cm.community_id=? ORDER BY cm.id LIMIT 500''',(cid,)).fetchall()
            return self.send_json(200,{'messages':[dict(x) for x in rows]})
        if p.path.startswith('/api/messages/'):
            u=self.user()
            if not u:return self.send_json(401,{'detail':'Войдите в аккаунт'})
            try: other=int(p.path.rsplit('/',1)[-1])
            except ValueError:return self.send_json(400,{'detail':'Неверный ID'})
            with connect() as c:
                rows=c.execute('''SELECT m.id,m.sender_id,m.recipient_id,m.body,m.attachment_json,m.created_at,m.reply_to_id,
                    EXISTS(SELECT 1 FROM pinned_messages p WHERE p.message_id=m.id AND p.user_id=?) AS pinned
                    FROM messages m
                    WHERE ((m.sender_id=? AND m.recipient_id=?) OR (m.sender_id=? AND m.recipient_id=?))
                    AND NOT EXISTS(SELECT 1 FROM message_hidden h WHERE h.message_id=m.id AND h.user_id=?)
                    ORDER BY m.id LIMIT 500''',(u['id'],u['id'],other,other,u['id'],u['id'])).fetchall()
            return self.send_json(200,{'messages':[dict(x) for x in rows]})
        return self.send_json(404,{'detail':'Не найдено'})
    def do_POST(self):
        p=urlparse(self.path)
        if p.path in ('/api/upload','/api/avatar'):
            u=self.user()
            if not u:return self.send_json(401,{'detail':'Войдите в аккаунт'})
            ctype=self.headers.get('Content-Type','')
            if not ctype.lower().startswith('multipart/form-data'):return self.send_json(400,{'detail':'Нужна multipart загрузка'})
            length=int(self.headers.get('Content-Length','0'))
            maxsize=15*1024*1024 if p.path=='/api/upload' else 3*1024*1024
            if length<=0 or length>maxsize+1024*1024:return self.send_json(413,{'detail':'Файл слишком большой (лимит 15 МБ для вложений, 3 МБ для аватара)'})
            raw=self.rfile.read(length)
            try:
                msg=BytesParser(policy=policy.default).parsebytes(('Content-Type: '+ctype+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+raw)
                part=next((x for x in msg.iter_parts() if x.get_filename()),None)
                if not part:return self.send_json(400,{'detail':'Файл не приложен'})
                blob=part.get_payload(decode=True) or b''; filename=part.get_filename(); mime=part.get_content_type()
                if not blob:return self.send_json(400,{'detail':'Пустой файл'})
                if p.path=='/api/avatar' and (not mime.startswith('image/') or len(blob)>3*1024*1024):return self.send_json(400,{'detail':'Аватар: только изображение до 3 МБ'})
                if p.path=='/api/upload' and (len(blob)>15*1024*1024 or not (mime.startswith(('image/','video/','audio/')) or mime in ('application/pdf','text/plain','application/zip','application/octet-stream'))):return self.send_json(400,{'detail':'Тип не поддерживается или превышен лимит 15 МБ'})
                ext=os.path.splitext(filename)[1][:12].lower(); safe=secrets.token_hex(16)+ext
                folder=os.path.join(BASE,'uploads'); os.makedirs(folder,exist_ok=True)
                with open(os.path.join(folder,safe),'wb') as f:f.write(blob)
                with connect() as db:db.execute('INSERT INTO uploads(filename,owner_id,content_type,size,created_at) VALUES(?,?,?,?,?)',(safe,u['id'],mime,len(blob),int(time.time())))
                url='/uploads/'+safe
                if p.path=='/api/avatar':
                    with connect() as db:db.execute('UPDATE users SET avatar=? WHERE id=?',(url,u['id']))
                    return self.send_json(200,{'ok':True,'url':url})
                return self.send_json(200,{'ok':True,'attachment':{'url':url,'name':filename[:180],'type':mime,'size':len(blob)}})
            except Exception as e:return self.send_json(400,{'detail':'Не удалось обработать файл: '+type(e).__name__})
        data=self.read_json()
        if data is None:return self.send_json(400,{'detail':'Некорректный запрос'})
        if p.path=='/api/register':
            username=str(data.get('username','')).strip().lower().lstrip('@'); email=str(data.get('email','')).strip().lower(); password=str(data.get('password','')); display=str(data.get('display_name','')).strip()
            if len(password)<8:return self.send_json(400,{'detail':'Пароль должен быть не короче 8 символов'})
            if not re.fullmatch(r'[a-z0-9_]{3,24}',username):return self.send_json(400,{'detail':'Юзернейм: 3–24 символа, латиница, цифры или _'})
            if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email):return self.send_json(400,{'detail':'Введите корректный email'})
            if not display or len(display)>40:return self.send_json(400,{'detail':'Введите имя (до 40 символов)'})
            salt=secrets.token_hex(16); digest=pw_hash(password,salt); uid=secrets.randbelow(80000000)+10000000
            try:
                with connect() as c:c.execute('INSERT INTO users(id,username,email,display_name,salt,passhash,created_at) VALUES(?,?,?,?,?,?,?)',(uid,username,email,display,salt,digest,int(time.time())))
            except sqlite3.IntegrityError:return self.send_json(409,{'detail':'Юзернейм или email уже занят'})
            return self.send_json(201,{'ok':True,'detail':'Аккаунт создан. Теперь войдите: после пароля придёт код на email.'})
        if p.path=='/api/login':
            identifier=str(data.get('username','')).strip().lower().lstrip('@'); password=str(data.get('password',''))
            with connect() as c:u=c.execute('SELECT * FROM users WHERE username=? OR email=?',(identifier,identifier)).fetchone()
            if not u or not secrets.compare_digest(pw_hash(password,u['salt']),u['passhash']):return self.send_json(401,{'detail':'Неверный юзернейм/email или пароль'})
            if not u['email']:return self.send_json(400,{'detail':'Для двухэтапного входа сначала добавьте email в настройки аккаунта'})
            code=f'{secrets.randbelow(1000000):06d}'; salt=secrets.token_hex(16); codehash=hashlib.sha256((salt+code).encode()).hexdigest(); now=int(time.time())
            with connect() as c:
                old=c.execute('SELECT sent_at FROM login_codes WHERE user_id=?',(u['id'],)).fetchone()
                if old and now-old['sent_at']<45:return self.send_json(429,{'detail':'Подождите 45 секунд перед повторной отправкой кода'})
                c.execute('INSERT OR REPLACE INTO login_codes(user_id,code_hash,salt,expires,attempts,sent_at) VALUES(?,?,?,?,0,?)',(u['id'],codehash,salt,now+300,now))
            try:send_login_code(u['email'],code)
            except Exception as e:
                print(f'[SMTP] Send failed: {type(e).__name__}: {e}', flush=True)
                with connect() as c:c.execute('DELETE FROM login_codes WHERE user_id=?',(u['id'],))
                return self.send_json(503,{'detail':'Не удалось отправить письмо. Смотрите строку [SMTP] в консоли сервера.'})
            return self.send_json(200,{'ok':True,'two_factor':True,'detail':'Код отправлен на почту','email_hint':mask_email(u['email'])})
        if p.path=='/api/verify-2fa':
            identifier=str(data.get('username','')).strip().lower().lstrip('@'); code=str(data.get('code','')).strip(); now=int(time.time())
            with connect() as c:
                u=c.execute('SELECT id FROM users WHERE username=? OR email=?',(identifier,identifier)).fetchone()
                challenge=c.execute('SELECT * FROM login_codes WHERE user_id=?',(u['id'],)).fetchone() if u else None
                if not challenge:return self.send_json(401,{'detail':'Сначала войдите с паролем и запросите код'})
                if challenge['expires']<now:return self.send_json(401,{'detail':'Код истёк. Войдите снова, чтобы получить новый.'})
                if challenge['attempts']>=5:
                    c.execute('DELETE FROM login_codes WHERE user_id=?',(u['id'],)); return self.send_json(429,{'detail':'Слишком много попыток. Войдите снова.'})
                expected=hashlib.sha256((challenge['salt']+code).encode()).hexdigest()
                if not secrets.compare_digest(expected,challenge['code_hash']):
                    c.execute('UPDATE login_codes SET attempts=attempts+1 WHERE user_id=?',(u['id'],)); return self.send_json(401,{'detail':'Неверный код'})
                c.execute('DELETE FROM login_codes WHERE user_id=?',(u['id'],))
            token=secrets.token_urlsafe(32)
            with connect() as c:c.execute('INSERT INTO sessions(token,user_id,expires) VALUES(?,?,?)',(token,u['id'],now+60*60*24*30))
            return self.send_json(200,{'ok':True,'token':token,'user_id':u['id']},[( 'Set-Cookie',f'{COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000')])
        if p.path=='/api/settings':
            u=self.user()
            if not u:return self.send_json(401,{'detail':'Войдите в аккаунт'})
            username=str(data.get('username',u['username'])).strip().lower().lstrip('@')
            email=str(data.get('email',u['email'] or '')).strip().lower()
            if not re.fullmatch(r'[a-z0-9_]{3,24}',username):return self.send_json(400,{'detail':'Юзернейм: 3–24 символа, латиница, цифры или _'})
            if email and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email):return self.send_json(400,{'detail':'Введите корректный email'})
            try:
                with connect() as c:c.execute('UPDATE users SET username=?,email=? WHERE id=?',(username,email or None,u['id']))
            except sqlite3.IntegrityError:
                return self.send_json(409,{'detail':'Этот юзернейм или email уже занят'})
            with connect() as c: fresh=c.execute('SELECT id,username,email,display_name,avatar,created_at FROM users WHERE id=?',(u['id'],)).fetchone()
            return self.send_json(200,{'ok':True,'user':dict(fresh)})
        if p.path=='/api/logout':
            auth=self.headers.get('Authorization','')
            token=auth[7:].strip() if auth.lower().startswith('bearer ') else None
            if not token:
                for part in self.headers.get('Cookie','').split(';'):
                    k,_,v=part.strip().partition('=')
                    if k==COOKIE:token=v
            if token:
                with connect() as c:c.execute('DELETE FROM sessions WHERE token=?',(token,))
            return self.send_json(200,{'ok':True},[( 'Set-Cookie',f'{COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0')])
        if p.path=='/api/chat-action':
            u=self.user()
            if not u:return self.send_json(401,{'detail':'Войдите в аккаунт'})
            try: other=int(data.get('other_id')); action=str(data.get('action',''))
            except (TypeError,ValueError):return self.send_json(400,{'detail':'ID чата некорректен'})
            if not c_user_exists(other):return self.send_json(404,{'detail':'Пользователь не найден'})
            with connect() as c:
                if action=='hide':c.execute('INSERT OR IGNORE INTO chat_hidden(user_id,other_id) VALUES(?,?)',(u['id'],other))
                elif action=='pin':c.execute('INSERT OR IGNORE INTO chat_pins(user_id,other_id) VALUES(?,?)',(u['id'],other))
                elif action=='unpin':c.execute('DELETE FROM chat_pins WHERE user_id=? AND other_id=?',(u['id'],other))
                elif action=='block':c.execute('INSERT OR IGNORE INTO blocked_users(user_id,other_id) VALUES(?,?)',(u['id'],other))
                elif action=='unblock':c.execute('DELETE FROM blocked_users WHERE user_id=? AND other_id=?',(u['id'],other))
                else:return self.send_json(400,{'detail':'Неизвестное действие'})
            return self.send_json(200,{'ok':True})
        if p.path=='/api/community-create':
            u=self.user()
            if not u:return self.send_json(401,{'detail':'Войдите в аккаунт'})
            name=str(data.get('name','')).strip()[:60]; kind=str(data.get('kind','group')); desc=str(data.get('description','')).strip()[:500]
            if kind not in ('group','channel'):return self.send_json(400,{'detail':'Тип должен быть group или channel'})
            if not name:return self.send_json(400,{'detail':'Укажите название'})
            with connect() as c:
                cur=c.execute('INSERT INTO communities(owner_id,name,kind,description,created_at) VALUES(?,?,?,?,?)',(u['id'],name,kind,desc,int(time.time())))
                cid=cur.lastrowid;c.execute('INSERT INTO community_members(community_id,user_id,role,joined_at) VALUES(?,?,?,?)',(cid,u['id'],'owner',int(time.time())))
            return self.send_json(201,{'ok':True,'community_id':cid})
        if p.path=='/api/community-invite':
            u=self.user()
            if not u:return self.send_json(401,{'detail':'Войдите в аккаунт'})
            try:cid=int(data.get('community_id'));target=int(data.get('user_id'))
            except (TypeError,ValueError):return self.send_json(400,{'detail':'ID сообщества или пользователя некорректен'})
            with connect() as c:
                co=c.execute('SELECT kind,owner_id FROM communities WHERE id=?',(cid,)).fetchone()
                member=c.execute('SELECT role FROM community_members WHERE community_id=? AND user_id=?',(cid,u['id'])).fetchone()
                if not co or not member or member['role'] not in ('owner','admin'):return self.send_json(403,{'detail':'Только администратор может добавлять участников'})
                if not c.execute('SELECT id FROM users WHERE id=?',(target,)).fetchone():return self.send_json(404,{'detail':'Пользователь не найден'})
                c.execute('INSERT OR IGNORE INTO community_members(community_id,user_id,role,joined_at) VALUES(?,?,?,?)',(cid,target,'member',int(time.time())))
            return self.send_json(200,{'ok':True})
        if p.path=='/api/community-send':
            u=self.user()
            if not u:return self.send_json(401,{'detail':'Войдите в аккаунт'})
            try:cid=int(data.get('community_id'));body=str(data.get('body','')).strip();attachment=data.get('attachment')
            except (TypeError,ValueError):return self.send_json(400,{'detail':'Некорректный запрос'})
            if (not body and not attachment) or len(body)>4000:return self.send_json(400,{'detail':'Сообщение пустое или слишком длинное'})
            if attachment and (not isinstance(attachment,dict) or not str(attachment.get('url','')).startswith('/uploads/')):return self.send_json(400,{'detail':'Некорректное вложение'})
            with connect() as c:
                member=c.execute('SELECT role FROM community_members WHERE community_id=? AND user_id=?',(cid,u['id'])).fetchone()
                community=c.execute('SELECT kind,owner_id FROM communities WHERE id=?',(cid,)).fetchone()
                if not member or not community:return self.send_json(403,{'detail':'Нет доступа к сообществу'})
                if community['kind']=='channel' and member['role'] not in ('owner','admin'):return self.send_json(403,{'detail':'Публиковать в канале может только администратор'})
                c.execute('INSERT INTO community_messages(community_id,sender_id,body,attachment_json,created_at) VALUES(?,?,?,?,?)',(cid,u['id'],body,json.dumps(attachment,ensure_ascii=False) if attachment else None,int(time.time())))
            return self.send_json(200,{'ok':True})
        if p.path=='/api/message-action':
            u=self.user()
            if not u:return self.send_json(401,{'detail':'Войдите в аккаунт'})
            try: mid=int(data.get('message_id')); action=str(data.get('action',''))
            except (TypeError,ValueError):return self.send_json(400,{'detail':'Неверный ID сообщения'})
            with connect() as c:
                m=c.execute('SELECT id,sender_id,recipient_id FROM messages WHERE id=? AND (sender_id=? OR recipient_id=?)',(mid,u['id'],u['id'])).fetchone()
                if not m:return self.send_json(404,{'detail':'Сообщение не найдено'})
                if action=='delete_all':
                    if m['sender_id']!=u['id']:return self.send_json(403,{'detail':'Удалить у обоих может только автор сообщения'})
                    c.execute('DELETE FROM messages WHERE id=?',(mid,))
                    c.execute('DELETE FROM pinned_messages WHERE message_id=?',(mid,))
                    c.execute('DELETE FROM message_hidden WHERE message_id=?',(mid,))
                elif action=='delete_me':
                    c.execute('INSERT OR IGNORE INTO message_hidden(message_id,user_id) VALUES(?,?)',(mid,u['id']))
                    c.execute('DELETE FROM pinned_messages WHERE message_id=? AND user_id=?',(mid,u['id']))
                elif action=='pin':
                    c.execute('INSERT OR IGNORE INTO pinned_messages(message_id,user_id) VALUES(?,?)',(mid,u['id']))
                elif action=='unpin':
                    c.execute('DELETE FROM pinned_messages WHERE message_id=? AND user_id=?',(mid,u['id']))
                else:return self.send_json(400,{'detail':'Неизвестное действие'})
            return self.send_json(200,{'ok':True})
        if p.path=='/api/forward':
            u=self.user()
            if not u:return self.send_json(401,{'detail':'Войдите в аккаунт'})
            try: mid=int(data.get('message_id')); recipient=int(data.get('recipient_id'))
            except (TypeError,ValueError):return self.send_json(400,{'detail':'Неверные ID'})
            with connect() as c:
                m=c.execute('SELECT body,attachment_json FROM messages WHERE id=? AND (sender_id=? OR recipient_id=?)',(mid,u['id'],u['id'])).fetchone()
                if not m:return self.send_json(404,{'detail':'Сообщение не найдено'})
                if not c.execute('SELECT id FROM users WHERE id=?',(recipient,)).fetchone():return self.send_json(404,{'detail':'Получатель не найден'})
                c.execute('INSERT INTO messages(sender_id,recipient_id,body,attachment_json,created_at) VALUES(?,?,?,?,?)',(u['id'],recipient,m['body'],m['attachment_json'],int(time.time())))
            return self.send_json(200,{'ok':True})
        if p.path=='/api/messages':
            u=self.user()
            if not u:return self.send_json(401,{'detail':'Войдите в аккаунт'})
            try: recipient=int(data.get('recipient_id')); body=str(data.get('body','')).strip(); attachment=data.get('attachment')
            except (ValueError,TypeError):return self.send_json(400,{'detail':'Неверный получатель'})
            if (not body and not attachment) or len(body)>4000:return self.send_json(400,{'detail':'Сообщение пустое или слишком длинное'})
            if attachment and (not isinstance(attachment,dict) or not str(attachment.get('url','')).startswith('/uploads/')):return self.send_json(400,{'detail':'Некорректное вложение'})
            if recipient==u['id']:return self.send_json(400,{'detail':'Нельзя отправить сообщение самому себе'})
            try: reply_to=int(data.get('reply_to_id')) if data.get('reply_to_id') else None
            except (TypeError,ValueError): reply_to=None
            with connect() as c:
                if not c.execute('SELECT id FROM users WHERE id=?',(recipient,)).fetchone():return self.send_json(404,{'detail':'Пользователь не найден'})
                if c.execute('SELECT 1 FROM blocked_users WHERE (user_id=? AND other_id=?) OR (user_id=? AND other_id=?) LIMIT 1',(u['id'],recipient,recipient,u['id'])).fetchone():return self.send_json(403,{'detail':'Переписка заблокирована'})
                c.execute('INSERT INTO messages(sender_id,recipient_id,body,attachment_json,created_at,reply_to_id) VALUES(?,?,?,?,?,?)',(u['id'],recipient,body,json.dumps(attachment,ensure_ascii=False) if attachment else None,int(time.time()),reply_to))
            return self.send_json(200,{'ok':True})
        return self.send_json(404,{'detail':'Не найдено'})

if __name__=='__main__':
    host=os.environ.get('HOST','0.0.0.0'); port=int(os.environ.get('PORT','8000'))
    print(f'Orbit запущен: http://{host}:{port}  (Ctrl+C для остановки)')
    ThreadingHTTPServer((host,port),Handler).serve_forever()

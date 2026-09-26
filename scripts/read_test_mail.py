import email,email.policy,re,sys,pathlib
files=sorted(pathlib.Path(sys.argv[1]).glob('*'),key=lambda p:p.stat().st_mtime)
if not files: raise SystemExit(1)
m=email.message_from_bytes(files[-1].read_bytes(),policy=email.policy.default)
text=m.get_body(preferencelist=('plain',)).get_content() if m.is_multipart() else m.get_content()
match=re.search(r'\b[0-9]{6}\b',text)
if not match: raise SystemExit(1)
print(match.group())

"""Valida a configuração local antes de iniciar o painel."""
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT / 'backend')
sys.path.insert(0, str(ROOT / 'backend'))
from dotenv import load_dotenv
load_dotenv(ROOT / 'backend' / '.env')

def main():
    problems = []
    url = os.getenv('DATABASE_URL', '')
    if not url:
        problems.append('Defina DATABASE_URL com a conexão do banco existente.')
    secret = os.getenv('JWT_SECRET_KEY', '')
    if len(secret) < 32 or secret.startswith('troque-'):
        problems.append('Defina JWT_SECRET_KEY com a mesma chave segura do backend existente (mínimo 32 caracteres).')
    ids = os.getenv('CENTRAL_ADMIN_IDS', '')
    if not ids or any(not value.strip().isdigit() for value in ids.split(',')):
        problems.append('Defina CENTRAL_ADMIN_IDS com os IDs reais dos administradores autorizados.')
    parsed = urlparse(url)
    if not parsed.scheme.startswith('postgres'):
        problems.append('Use o PostgreSQL existente. SQLite é permitido somente nos testes isolados.')
    if parsed.hostname not in {'localhost', '127.0.0.1', '::1', None}:
        if parse_qs(parsed.query).get('sslmode', [''])[0] != 'verify-full':
            problems.append('Banco remoto exige sslmode=verify-full e certificado confiável configurado.')
    if problems:
        print('Configuração pendente:\n- ' + '\n- '.join(problems))
        return 1
    from app.database import SessionLocal
    from app.central.policy import installed, admins
    from app.models.usuario import Usuario
    with SessionLocal() as db:
        if not installed(db):
            print('Migração central não aplicada. Faça backup e revise a migração 0011 antes de executá-la.')
            return 1
        if db.query(Usuario).filter(Usuario.id.in_(admins()), Usuario.perfil_id == 'administrador', Usuario.ativo.is_(True)).count() < 1:
            print('Nenhum administrador autorizado ativo encontrado no banco existente.')
            return 1
    import uvicorn
    print('Painel separado: http://127.0.0.1:8765 — use o login existente.')
    uvicorn.run('app.central.main:app', host='127.0.0.1', port=8765, workers=1, proxy_headers=False, server_header=False)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

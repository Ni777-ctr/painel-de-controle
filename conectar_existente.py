"""Abre o painel separado usando o backend local já configurado."""
import os
import sys
from pathlib import Path

DEFAULT_BACKEND = Path(os.environ.get('ELETROGESTOR_BACKEND', 'backend'))

def main():
    backend = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_BACKEND
    if not (backend / '.env').is_file() or not (backend / 'app/central/main.py').is_file():
        raise SystemExit('Backend não configurado ou integração central ausente.')
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    from dotenv import load_dotenv
    load_dotenv(backend / '.env')
    from app.config import get_settings
    from app.database import SessionLocal
    from app.central.policy import installed, admins
    from app.models.usuario import Usuario
    settings = get_settings()
    if len(settings.JWT_SECRET_KEY) < 32 or settings.JWT_SECRET_KEY.startswith('troque-'):
        raise SystemExit('Configure uma chave JWT segura no backend principal antes de iniciar.')
    if settings.DATABASE_URL.startswith('sqlite'):
        if settings.em_producao:
            raise SystemExit('SQLite habilitado somente para o ambiente local existente.')
        from sqlalchemy.engine import make_url
        database = make_url(settings.DATABASE_URL).database
        if not database or database == ':memory:' or not Path(database).is_file():
            raise SystemExit('Banco local existente não encontrado; nenhum banco será criado.')
    with SessionLocal() as db:
        if not installed(db):
            raise SystemExit('Integração central ainda não instalada no banco existente.')
        if not db.query(Usuario).filter(Usuario.id.in_(admins()), Usuario.perfil_id == 'administrador', Usuario.ativo.is_(True)).count():
            raise SystemExit('Nenhum administrador existente autorizado para o painel.')
        print(f'Banco existente conectado: {db.query(Usuario).count()} usuários.')
    import uvicorn
    print('Painel separado: http://127.0.0.1:8765 — use seu login existente.')
    uvicorn.run('app.central.main:app', host='127.0.0.1', port=8765, workers=1,
                proxy_headers=False, server_header=False)

if __name__ == '__main__':
    main()

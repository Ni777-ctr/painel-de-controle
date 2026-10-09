"""Concede (ou retira) as permissoes do modulo Supervisao nos perfis EXISTENTES.

Seguro para bancos com dados reais/copia de homologacao: NAO cria usuarios, NAO cria
dados de demonstracao e NAO remove nenhuma outra permissao. Idempotente (rodar N vezes
= mesmo resultado). Perfis com "*" nao sao tocados; perfis ausentes sao apenas avisados.

Uso (a partir da pasta backend/):
    PYTHONPATH=. python seeds/seed_supervisao.py --dry-run     # mostra o que mudaria
    PYTHONPATH=. python seeds/seed_supervisao.py               # aplica (soma as chaves)
    PYTHONPATH=. python seeds/seed_supervisao.py --reverter    # retira so supervisao:read/write

Mapa por perfil: seeds/seed.py -> PERMISSOES_SUPERVISAO_POR_PERFIL.
"""
import argparse

from sqlalchemy.orm import Session

from app.models.usuario import Perfil
from seeds.seed import PERMISSOES_SUPERVISAO, PERMISSOES_SUPERVISAO_POR_PERFIL


def aplicar(db: Session, *, reverter: bool = False, dry_run: bool = False) -> list[str]:
    """Aplica (ou reverte) as permissoes de Supervisao. Retorna linhas descrevendo cada mudanca."""
    mudancas: list[str] = []
    for perfil_id, chaves in PERMISSOES_SUPERVISAO_POR_PERFIL.items():
        perfil = db.get(Perfil, perfil_id)
        if perfil is None:
            mudancas.append(f"AVISO perfil '{perfil_id}' nao existe (ignorado)")
            continue
        atuais = list(perfil.permissoes or [])
        if "*" in atuais:
            continue  # acesso total: nada a fazer
        if reverter:
            novas = [p for p in atuais if p not in PERMISSOES_SUPERVISAO]
        else:
            novas = atuais + [p for p in chaves if p not in atuais]
        if novas != atuais:
            mudancas.append(f"{'-' if reverter else '+'} {perfil_id}: {sorted(set(novas) ^ set(atuais))}")
            if not dry_run:
                perfil.permissoes = novas
    if not dry_run:
        db.commit()
    return mudancas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reverter", action="store_true", help="retira supervisao:read/write dos perfis")
    parser.add_argument("--dry-run", action="store_true", help="apenas mostra o que seria alterado")
    args = parser.parse_args()

    from app.database import SessionLocal  # import tardio: so conecta ao rodar como script

    db = SessionLocal()
    try:
        mudancas = aplicar(db, reverter=args.reverter, dry_run=args.dry_run)
    finally:
        db.close()
    prefixo = "[dry-run] " if args.dry_run else ""
    for linha in mudancas or ["nenhuma alteracao necessaria (ja esta como esperado)"]:
        print(prefixo + linha)


if __name__ == "__main__":
    main()

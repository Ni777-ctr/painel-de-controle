"""Inspeção por padrão; aplicação explícita com backup e hashes de compatibilidade."""
import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--destino', required=True, help='Pasta backend do projeto principal')
    parser.add_argument('--aplicar', action='store_true', help='Aplicar alterações após backup')
    args = parser.parse_args()
    destination = Path(args.destino).resolve()
    if destination == (ROOT / 'backend').resolve():
        raise SystemExit('Destino deve ser o backend principal, não a cópia incluída neste pacote.')
    manifest = json.loads((ROOT / 'integracao-manifesto.json').read_text(encoding='utf-8'))
    for relative, digest in manifest['originais'].items():
        target = destination / relative
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise SystemExit(f'Arquivo diferente da versão enviada: {relative}. Integre manualmente pelo patch; nenhuma alteração foi aplicada.')
    for relative in manifest['novos']:
        if (destination / relative).exists():
            raise SystemExit(f'O destino já contém {relative}. Revise a integração manualmente; nenhuma alteração foi aplicada.')
    files = list(manifest['originais']) + manifest['novos']
    print('Arquivos de integração:\n' + '\n'.join(files))
    if not args.aplicar:
        print('\nInspeção concluída. Nenhum arquivo alterado. Use --aplicar somente após revisar e fazer backup do banco.')
        return
    backup = ROOT / 'backups' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    for relative in manifest['originais']:
        target = backup / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destination / relative, target)
    (backup / 'arquivos-novos.json').write_text(json.dumps(manifest['novos'],indent=2),encoding='utf-8')
    for relative in files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / 'backend' / relative, target)
    print(f'Integração aplicada. Backup das fontes anteriores em {backup}. Nenhum comando de banco foi executado.')
    print('Para desfazer fontes: restaure os arquivos desse backup e remova apenas os arquivos listados em arquivos-novos.json, depois reinicie o backend.')

if __name__ == '__main__':
    main()

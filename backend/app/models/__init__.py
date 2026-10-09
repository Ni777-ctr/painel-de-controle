"""Reune todos os modelos para que Base.metadata os enxergue (Alembic autogenerate)."""
from app.models.auditoria import AuditLog  # noqa: F401
from app.models.automacao import (  # noqa: F401
    Automacao,
    ExecucaoAutomacao,
    EventoSelfHealing,
    LeituraSubestacao,
    PontoVegetacao,
    Subestacao,
)
from app.models.cliente import Cliente  # noqa: F401
from app.models.compras import (  # noqa: F401
    Fornecedor,
    PedidoCompra,
    PedidoCompraItem,
    RequisicaoCompra,
    RequisicaoCompraItem,
)
from app.models.equipe import Equipe, EquipeMembro  # noqa: F401
from app.models.estoque import Almoxarifado, EstoqueItem, Material, MovimentacaoEstoque  # noqa: F401
from app.models.financeiro import AlertaFinanceiro, Fatura, Glosa, Medicao, Pagamento  # noqa: F401
from app.models.frota import ManutencaoVeiculo, Veiculo  # noqa: F401
from app.models.planilha import ExecucaoObra, GeradorProgramacao, InventarioObra, SigeoExtracao  # noqa: F401
from app.models.notificacao import Notificacao  # noqa: F401
from app.models.obra import HistoricoStatusObra, Obra, Programacao  # noqa: F401
from app.models.parametro import ParametroGlobal  # noqa: F401
from app.models.relatorio import RelatorioGerado  # noqa: F401
from app.models.supervisao import Empreiteira, RelatorioSupervisao  # noqa: F401
from app.models.usuario import Perfil, RefreshToken, Usuario  # noqa: F401

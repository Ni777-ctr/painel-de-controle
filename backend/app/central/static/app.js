'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const moduleLabels = {programacao:'Programação',automacoes:'Automações',notificacoes:'Notificações',auditoria:'Auditoria',usuarios:'Usuários',parametros:'Parâmetros',supervisao:'Supervisão',relatorios:'Relatórios',equipes:'Equipes',estoque:'Estoque',compras:'Compras',financeiro:'Financeiro',frota:'Frota',obras:'Obras',clientes:'Clientes',dashboard:'Visão geral'};
const title = value => moduleLabels[value] || String(value ?? '').replace(/(^|[ -])\p{L}/gu, char => char.toUpperCase());
const pages = [['overview','Visão geral','◫'],['users','Usuários','♙'],['roles','Cargos e liberações','▣'],['sectors','Setores','▤'],['permissions','Permissões','◇'],['hierarchy','Hierarquia e equipes','♧'],['history','Histórico de atividades','◷'],['security','Segurança e configurações','⚙']];
let state, csrf = '', actor, currentPage = 'overview', historyPage = 1, lastHistory, loginStage = 'login';
let filters = {search:'', cargo:'', estado:''};
let modalSubmit;
const names = list => list.map(x=>esc(title(x))).join(', ');
const sectorName = sid => state.setores.find(s=>s.id===Number(sid))?.nome || `Setor #${sid}`;
const userName = uid => state.usuarios.find(u=>u.id===Number(uid))?.nome || (uid ? `Usuário #${uid}` : 'Sem responsável');
const status = value => `<span class="status ${['ativo','pendente','bloqueado','desativado'].includes(value)?value:'neutral'}">${esc(title(value))}</span>`;
const field = (name, label, value='', type='text', extra='') => `<label>${esc(label)}<input name="${name}" type="${type}" value="${esc(value)}" ${extra}></label>`;
const options = (list, selected, empty) => (empty !== undefined ? `<option value="">${esc(empty)}</option>` : '') + list.map(([value,label])=>`<option value="${esc(value)}" ${String(value)===String(selected)?'selected':''}>${esc(label)}</option>`).join('');
const select = (name,label,list,selected='',empty) => `<label>${esc(label)}<select name="${name}">${options(list,selected,empty)}</select></label>`;
const check = (name,label,checked=false,value='on') => `<label><input type="checkbox" name="${name}" value="${esc(value)}" ${checked?'checked':''}>${esc(label)}</label>`;
function toast(message) { $('#toast').textContent=message; $('#toast').hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>$('#toast').hidden=true,6500); }
async function api(path, method='GET', body) {
 const headers = {'Content-Type':'application/json'}; if(csrf) headers['X-CSRF-Token']=csrf;
 const response = await fetch('/api'+path,{method,headers,credentials:'same-origin',body:body===undefined?undefined:JSON.stringify(body)});
 let data; try { data=await response.json(); } catch { data={detail:'O servidor não respondeu. Verifique a configuração e a conexão com o banco.'}; }
 if(!response.ok) {
  if(response.status===401 && !path.startsWith('/login')) showLogin();
  throw new Error(Array.isArray(data.detail)?data.detail.map(e=>`${e.loc?.slice(1).join('.')}: ${e.msg}`).join('\n'):(data.detail||'Não foi possível realizar a operação.'));
 }
 return data;
}
function showLogin() { csrf=''; state=undefined; actor=undefined; $('#workspace').hidden=true; $('#login').hidden=false; }
async function refresh() { state=await api('/dados'); $('#updated').textContent='Atualizado às '+new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'}); await render(); }
async function enter(session) {
 csrf=session.csrf; actor=session; $('#actor-name').textContent=session.nome;
 $('.avatar').textContent=session.nome?.charAt(0).toUpperCase()||'A';
 await refresh(); $('#login').hidden=true; $('#workspace').hidden=false;
}
$('#login-form').addEventListener('submit',async event=>{
 event.preventDefault(); const form=event.currentTarget, button=$('button[type=submit]',form); button.disabled=true; $('#login-error').textContent='';
 try {
  const values=Object.fromEntries(new FormData(form));
  const result=await api(loginStage==='login'?'/login':'/login/continuar','POST',values);
  form.reset();
  if(result.etapa==='concluido') { loginStage='login'; await enter(await api('/session')); restoreLogin(); }
  else { loginStage=result.etapa; const input=result.etapa==='mfa'?field('codigo','Código do autenticador','','text','required inputmode="numeric" pattern="[0-9]{6}" autocomplete="one-time-code"'):field('nova_senha','Nova senha','','password','required minlength="12" maxlength="72" autocomplete="new-password"'); form.innerHTML=`<div class="eyebrow">VERIFICAÇÃO DE ACESSO</div><h2>${result.etapa==='mfa'?'Confirmar identidade':'Atualizar senha'}</h2><p class="muted">${esc(result.mensagem)}</p>${input}<button class="primary" type="submit">Continuar</button><button type="button" data-action="restart-login">Voltar ao login</button><p id="login-error" class="error" role="alert"></p>`; }
 } catch(error) { $('#login-error').textContent=error.message; if(loginStage!=='login') setTimeout(()=>{restoreLogin(); $('#login-error').textContent=error.message+' Entre novamente.';},2500); }
 finally { button.disabled=false; }
});
const initialLogin = $('#login-form').innerHTML;
function restoreLogin() { loginStage='login'; $('#login-form').innerHTML=initialLogin; }
$('#login-form').addEventListener('click',event=>{if(event.target.closest('[data-action="restart-login"]'))restoreLogin();});
$('#logout').addEventListener('click',async()=>{try{await api('/logout','POST',{});showLogin();restoreLogin();}catch(e){toast(e.message);}});
$('#menu').addEventListener('click',()=>$('#sidebar').classList.toggle('open'));
$('#navigation').innerHTML=pages.map(([key,label,icon])=>`<button data-page="${key}"><span class="nav-icon" aria-hidden="true">${icon}</span>${label}</button>`).join('');
$('#navigation').addEventListener('click',async event=>{const button=event.target.closest('[data-page]');if(button){currentPage=button.dataset.page;$('#sidebar').classList.remove('open');try{await render();}catch(e){toast(e.message);}}});
function head(name,description,action='') { return `<div class="page-head"><div><div class="eyebrow">CONTROLE CENTRAL</div><h1>${esc(name)}</h1><p>${esc(description)}</p></div>${action}</div>`; }
function table(headers, rows) {return `<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th scope="col">${h}</th>`).join('')}</tr></thead><tbody>${rows.length?rows.join(''):`<tr><td colspan="${headers.length}" class="empty">Nenhum registro encontrado.</td></tr>`}</tbody></table></div>`;}
function recentRows(items) {return items.map(log=>`<tr><td>${esc(log.acao.replace(/^central_/,'').replaceAll('_',' '))}<small>${esc(log.entidade)} #${esc(log.entidade_id||'—')}</small></td><td>${esc(userName(log.usuario_id))}</td><td>${esc(new Date(log.criado_em).toLocaleString('pt-BR'))}</td><td><button data-action="audit-detail" data-id="${log.id}">Detalhes</button></td></tr>`);}
async function render() {
 if(!state)return;
 $('#breadcrumb').textContent=pages.find(p=>p[0]===currentPage)[1];
 $$('#navigation button').forEach(b=>b.classList.toggle('active',b.dataset.page===currentPage));
 const output=$('#content');
 if(currentPage==='overview') {
  const all=state.total; const count=c=>state.usuarios.filter(u=>u.cargo===c).length;
  const unmanaged=state.usuarios.filter(u=>!u.gerenciado).length;
  output.innerHTML=head('Visão geral','Pessoas, acessos e disponibilidade em um só lugar.',`<span class="subtle-badge">${state.modo_teste?'TESTE ISOLADO · DADOS SINTÉTICOS':'BANCO COMPARTILHADO'}</span>`)+
   `<div class="metrics">${[['Total de usuários',all,'Todos os cadastros existentes'],['Contas ativas',state.estados.ativo,'Acesso habilitado'],['Bloqueados / desativados',state.estados.bloqueado+state.estados.desativado,'Histórico preservado'],['Ativação pendente',state.estados.pendente,'Aguardando definição de senha']].map(([label,value,detail])=>`<div class="metric"><div class="metric-label">${label}</div><strong>${value}</strong><small>${detail}</small></div>`).join('')}</div>`+
   (unmanaged?`<div class="notice info">${unmanaged} usuário(s) ainda sem cargo e vínculos no controle central. Revise cada cadastro na aba Usuários; o painel não atribui cargos automaticamente.</div>`:'')+
   `<div class="grid-two"><section class="panel"><div class="panel-head"><h2>Distribuição por cargo</h2><button data-page="users" class="text-button">Ver usuários</button></div>${state.cargos.map(c=>`<div class="role-row"><span>${title(c)}</span><progress value="${count(c)}" max="${Math.max(all,1)}" aria-label="${title(c)}"></progress><b>${count(c)}</b></div>`).join('')}<p class="help">Contagem de usuários vinculados ao controle central.</p></section><section class="panel"><div class="panel-head"><h2>Disponibilidade de cadastros</h2><button data-page="roles" class="text-button">Configurar</button></div>${state.limites.filter(l=>!l.setor_id).map(l=>`<div class="settings-row"><span>${title(l.cargo)}<small class="muted"> · ${l.utilizado} / ${l.maximo}</small></span>${l.habilitado?`<span class="status ${l.disponivel?'ativo':'pendente'}">${l.disponivel} vaga(s)</span>`:status('desativado')}</div>`).join('')||'<div class="empty">Nenhum limite aprovado.<br>Configure os limites para liberar novos cadastros.</div>'}<p class="help">Convites pendentes reservam vagas para evitar ultrapassar os limites.</p></section></div>`+
   `<section class="panel"><div class="panel-head"><h2>Usuários por setor</h2></div>${table(['Setor','Vinculados','Estado'],state.setores.map(s=>`<tr><td>${esc(s.nome)}</td><td>${state.usuarios.filter(u=>u.vinculos.some(v=>v.setor_id===s.id)).length}</td><td>${status(s.ativo?'ativo':'desativado')}</td></tr>`))}</section><section class="panel"><div class="panel-head"><h2>Atividades recentes</h2><button data-page="history" class="text-button">Ver histórico</button></div><div id="recent-history" class="loading">Carregando atividades…</div></section>`;
  const history=await api('/historico');lastHistory=history.itens;$('#recent-history').innerHTML=table(['Alteração','Autor','Data',''],recentRows(history.itens.slice(0,5)));
 } else if(currentPage==='users') renderUsers();
 else if(currentPage==='roles') output.innerHTML=head('Cargos e liberações','Limites globais e por setor, aprovados pelo administrador.','<button class="primary" data-action="limit-new">Configurar limite</button>')+
  (state.limites.some(l=>l.utilizado>l.maximo)?'<div class="notice">Há limites abaixo da quantidade utilizada. Novos cadastros e reativações ficam bloqueados; nenhuma conta é desativada automaticamente.</div>':'')+
  `<section class="panel">${table(['Cargo','Contexto','Utilização','Disponíveis','Liberação','Alerta',''],state.limites.map(l=>`<tr><td><b>${title(l.cargo)}</b></td><td>${l.setor_id?esc(sectorName(l.setor_id)):'Empresa inteira'}</td><td>${l.utilizado} / ${l.maximo}</td><td>${l.disponivel}</td><td>${status(l.habilitado?'ativo':'desativado')}</td><td>${l.alerta?'<span class="status pendente">Atenção</span>':'—'}</td><td><button data-action="limit-edit" data-cargo="${l.cargo}" data-sid="${l.setor_id}">Editar</button></td></tr>`))}<p class="help">Cada cargo exige um limite global aprovado. O limite por setor é opcional. Desabilitar impede cadastros e reativações, preservando as contas atuais.</p></section>`+
  `<section class="panel"><h2>Delegação de cadastro</h2>${table(['Cargo','Pode cadastrar','Escopo'],[['Dono','Gerentes','Setores vinculados'],['Gerente','Coordenadores e colaboradores','Setores vinculados'],['Coordenador','Colaboradores','Própria responsabilidade'],['Colaborador','Nenhum usuário','Operações autorizadas']].map(row=>`<tr>${row.map(c=>`<td>${c}</td>`).join('')}</tr>`))}<p class="help">A delegação precisa ser habilitada no limite global do cargo de quem cadastra. A API compartilhada valida cargo, setor e responsável.</p></section>`;
 else if(currentPage==='sectors') output.innerHTML=head('Setores','Contextos de trabalho, módulos e cargos autorizados.','<button class="primary" data-action="sector-new">Novo setor</button>')+
  `<div class="card-grid">${state.setores.map(s=>`<article class="sector-card">${status(s.ativo?'ativo':'desativado')}<h2>${esc(s.nome)}</h2><p>${esc(s.descricao||'Sem descrição')}</p><div class="tags">${s.modulos.map(m=>`<span class="tag">${esc(title(m))}</span>`).join('')}</div><p>${state.usuarios.filter(u=>u.vinculos.some(v=>v.setor_id===s.id)).length} usuário(s) vinculado(s)<br><small>${names(s.cargos)}</small></p><button data-action="sector-edit" data-id="${s.id}">Editar setor</button></article>`).join('')||'<div class="panel empty">Nenhum setor criado. Cadastre os setores reais da empresa.</div>'}</div>`;
 else if(currentPage==='permissions') renderPermissions();
 else if(currentPage==='hierarchy') {
  const issues=[];
  state.usuarios.filter(u=>u.gerenciado&&!u.vinculos.length).forEach(u=>issues.push(`${u.nome}: sem vínculo de setor.`));
  state.usuarios.forEach(u=>u.vinculos.forEach(v=>{if(v.cargo!=='dono'&&!state.usuarios.some(p=>p.id===v.responsavel_id&&p.estado==='ativo'&&p.vinculos.some(pv=>pv.setor_id===v.setor_id&&state.cargos.indexOf(pv.cargo)<state.cargos.indexOf(v.cargo))))issues.push(`${u.nome}: responsável inválido no setor ${sectorName(v.setor_id)}.`);}));
  output.innerHTML=head('Hierarquia e equipes','Vínculos independentes em cada setor. Dono → Gerente → Coordenador → Colaborador.')+
  (issues.length?`<div class="notice"><b>${issues.length} vínculo(s) para revisar</b><ul>${issues.map(i=>`<li>${esc(i)}</li>`).join('')}</ul></div>`:'')+
  state.setores.map(s=>`<section class="panel"><div class="panel-head"><h2>${esc(s.nome)}</h2>${status(s.ativo?'ativo':'desativado')}</div>${state.usuarios.filter(u=>u.vinculos.some(v=>v.setor_id===s.id)).sort((a,b)=>state.cargos.indexOf(a.vinculos.find(v=>v.setor_id===s.id).cargo)-state.cargos.indexOf(b.vinculos.find(v=>v.setor_id===s.id).cargo)).map(u=>{const v=u.vinculos.find(v=>v.setor_id===s.id);return `<div class="hierarchy-row level-${state.cargos.indexOf(v.cargo)}"><div><strong>${esc(u.nome)}</strong> <span class="tag">${title(v.cargo)}</span><small>Responsável: ${esc(userName(v.responsavel_id))}</small></div><button data-action="user-edit" data-id="${u.id}">Editar vínculo</button></div>`;}).join('')||'<div class="empty">Nenhum usuário vinculado.</div>'}</section>`).join('');
  if(!state.setores.length)output.innerHTML+='<div class="panel empty">Crie um setor para organizar as equipes.</div>';
 } else if(currentPage==='history') {
  const history=await api('/historico?pagina='+historyPage);lastHistory=history.itens;
  output.innerHTML=head('Histórico de atividades','Registro de alterações e tentativas de acesso. Os registros não podem ser editados pelo painel.')+`<section class="panel">${table(['Alteração','Autor','Data',''],recentRows(history.itens))}<div class="pagination"><button data-action="history-prev" ${historyPage===1?'disabled':''}>Anterior</button><span>Página ${historyPage} · ${history.total} registros</span><button data-action="history-next" ${historyPage*50>=history.total?'disabled':''}>Próxima</button></div></section>`;
 } else if(currentPage==='security') output.innerHTML=head('Segurança e configurações','Proteção do painel e integração com o sistema principal.')+
  `<div class="grid-two"><section class="panel"><h2>Acesso administrativo</h2><div class="settings-row"><span>Administrador conectado</span><b>${esc(actor.nome)}</b></div><div class="settings-row"><span>IDs autorizados no servidor</span><b>${state.administradores.join(', ')||'Não configurados'}</b></div><div class="settings-row"><span>Validade da sessão</span><b>1 hora</b></div><div class="settings-row"><span>Proteção de operações</span><b>Sessão + CSRF</b></div><p class="help">A lista de administradores é definida nas variáveis de ambiente do servidor. Não existe cadastro público de administradores.</p></section><section class="panel"><h2>Conexão e execução</h2><div class="settings-row"><span>Endereço local</span><b>127.0.0.1:8765</b></div><div class="settings-row"><span>Autenticação</span><b>Contas existentes</b></div><div class="settings-row"><span>Senhas no banco</span><b>Hash bcrypt</b></div><div class="settings-row"><span>Exclusão definitiva</span><b>Indisponível</b></div><p class="help">Backup, restauração e migrações são operações externas documentadas no README. A interface não executa restaurações nem apaga históricos.</p></section></div><div class="notice">A integração do backend original é necessária para revogar tokens de acesso e proteger as rotas antigas. Registros operacionais ainda não possuem escopo de setor: usuários gerenciados têm acesso negado nessas rotas até a integração de cada módulo.</div>`;
}
function $$(selector,root=document){return [...root.querySelectorAll(selector)];}
function renderUsers() {
 $('#content').innerHTML=head('Usuários','Cadastros existentes, estados da conta e vínculos de acesso.','<button class="primary" data-action="user-new">Convidar usuário</button>')+
 `<div class="toolbar"><input id="user-search" aria-label="Pesquisar usuários" placeholder="Buscar nome, e-mail, login, ID ou setor" value="${esc(filters.search)}"><select id="user-role" aria-label="Filtrar cargo">${options(state.cargos.map(c=>[c,title(c)]),filters.cargo,'Todos os cargos')}</select><select id="user-state" aria-label="Filtrar estado">${options(['ativo','bloqueado','desativado','pendente'].map(s=>[s,title(s)]),filters.estado,'Todos os estados')}</select></div><section class="panel" id="user-table"></section>`;
 const update=()=>{
  const q=filters.search.toLocaleLowerCase('pt-BR');
  const users=state.usuarios.filter(u=>(!filters.cargo||u.cargo===filters.cargo)&&(!filters.estado||u.estado===filters.estado)&&[u.nome,u.email,u.usuario,u.id,...u.vinculos.map(v=>sectorName(v.setor_id))].join(' ').toLocaleLowerCase('pt-BR').includes(q));
  $('#user-table').innerHTML=table(['Usuário','Cargo / perfil','Setores','Estado',''],users.map(u=>`<tr><td><span class="user-cell">${esc(u.nome)}</span><small>${esc(u.email||u.usuario)} · #${u.id}</small></td><td>${u.cargo?title(u.cargo):'<span class="muted">Não configurado</span>'}<small>${esc(u.perfil_id)}</small></td><td>${u.vinculos.map(v=>esc(sectorName(v.setor_id))).join(', ')||'—'}</td><td>${status(u.estado)}</td><td><button data-action="user-edit" data-id="${u.id}">Gerenciar</button></td></tr>`));
 };
 $('#user-search').addEventListener('input',e=>{filters.search=e.target.value;update();});$('#user-role').addEventListener('change',e=>{filters.cargo=e.target.value;update();});$('#user-state').addEventListener('change',e=>{filters.estado=e.target.value;update();});update();
}
function renderPermissions() {
 $('#content').innerHTML=head('Permissões','Regras por cargo e setor, com exceções individuais de três estados.','<button class="primary" data-action="permission-new">Editar permissão</button>')+
 `<div class="notice info">As ações correspondem às permissões existentes na API. Onde o legado usa “write”, criar, editar e excluir compartilham a mesma permissão.</div><section class="panel"><div class="panel-head"><h2>Padrões por cargo e setor</h2></div>${table(['Setor','Cargo','Permissão','Regra'],state.regras.map(r=>`<tr><td>${esc(sectorName(r.setor_id))}</td><td>${title(r.cargo)}</td><td>${esc(r.permissao)}</td><td>${status(r.permitido?'ativo':'bloqueado')}</td></tr>`))}<p class="help">Ausência de regra significa acesso negado.</p></section><section class="panel"><div class="panel-head"><h2>Exceções individuais</h2></div>${table(['Usuário','Setor','Permissão','Exceção'],state.excecoes.map(r=>`<tr><td>${esc(userName(r.usuario_id))}</td><td>${esc(sectorName(r.setor_id))}</td><td>${esc(r.permissao)}</td><td>${r.permitido?'Permitido':'Negado'}</td></tr>`))}</section><section class="panel"><h2>Consultar acesso efetivo</h2><div class="form-grid">${select('effective-user','Usuário',state.usuarios.map(u=>[u.id,u.nome]))}${select('effective-sector','Setor',state.setores.map(s=>[s.id,s.nome]))}</div><button data-action="effective">Consultar permissões</button><div id="effective-result"></div></section>`;
}
function modal(name,html,submit) {
 $('#modal-title').textContent=name;$('#modal-body').innerHTML=html;modalSubmit=submit;
 if(!$('#modal').open)$('#modal').showModal();
}
$('#close-modal').addEventListener('click',()=>$('#modal').close());
const approval = `<div class="confirm-block"><label>Justificativa<textarea name="justificativa" required minlength="5" maxlength="500" placeholder="Descreva o motivo desta alteração"></textarea></label><label class="confirm-label"><input name="confirmar" type="checkbox" required>Confirmo a alteração no banco compartilhado.</label></div><p class="error" id="form-error" role="alert"></p><div class="form-actions"><button type="button" data-action="cancel">Cancelar</button><button type="submit" class="primary">Confirmar e salvar</button></div>`;
function confirmedForm(html) {return `<form id="edit-form">${html}${approval}</form>`;}
$('#modal-body').addEventListener('submit',async event=>{
 event.preventDefault();const form=event.target;if(form.id!=='edit-form')return;
 const button=$('button[type=submit]',form);button.disabled=true;$('#form-error').textContent='';
 try { const data=Object.fromEntries(new FormData(form));data.confirmar=Boolean(data.confirmar);await modalSubmit(data,form);$('#modal').close();await refresh();toast('Alteração salva e registrada no histórico.'); }
 catch(error){$('#form-error').textContent=error.message;}finally{button.disabled=false;}
});
function userModal(uid=0) {
 const u=state.usuarios.find(x=>x.id===uid)||{nome:'',usuario:'',email:'',cargo:'colaborador',perfil_id:'',estado:'pendente',vinculos:[]};
 const row=v=>`<div class="link-row"><select name="link-sector" aria-label="Setor do vínculo" required>${options(state.setores.map(s=>[s.id,s.nome]),v.setor_id,'Setor')}</select><select name="link-role" aria-label="Cargo no setor">${options(state.cargos.map(c=>[c,title(c)]),v.cargo||u.cargo)}</select><select name="link-parent" aria-label="Responsável hierárquico">${options(state.usuarios.filter(x=>x.id!==uid).map(x=>[x.id,x.nome]),v.responsavel_id,'Sem responsável')}</select><button type="button" data-action="remove-link" aria-label="Remover vínculo">×</button></div>`;
 modal(uid?'Gerenciar usuário':'Convidar usuário',confirmedForm(
  `<div class="form-grid">${field('nome','Nome completo',u.nome,'text','required maxlength="120"')}${field('usuario','Identificador de login',u.usuario,'text',`required maxlength="60" ${uid?'readonly':''}`)}${field('email','E-mail',u.email,'email','maxlength="160"')}${select('perfil_id','Perfil existente no sistema',state.perfis.map(p=>[p.id,p.nome]),u.perfil_id,'Selecione um perfil')}${select('cargo','Cargo central',state.cargos.map(c=>[c,title(c)]),u.cargo)}${select('estado','Estado da conta',(uid?['ativo','bloqueado','desativado','pendente']:['pendente']).map(s=>[s,title(s)]),u.estado)}</div>`+
  (uid?`<p class="help">Cadastrado por: ${esc(userName(u.criado_por))}${u.criado_por?'':' (origem não registrada no legado)'}. MFA: ${u.mfa?'habilitado':'não habilitado'}.</p>`:'<div class="notice info">O usuário define a própria senha por convite. A vaga fica reservada até a ativação.</div>')+
  `<h3>Setores e responsáveis</h3><div id="link-list">${u.vinculos.map(row).join('')}</div><button type="button" data-action="add-link">Adicionar vínculo</button>`+
  (uid?`<div class="form-actions"><button type="button" data-action="sessions" data-id="${uid}">Encerrar sessões</button><button type="button" data-action="password" data-id="${uid}">Redefinir senha por convite</button></div><p class="help">Bloqueio e desativação preservam o histórico. As alterações de acesso encerram sessões da conta.</p>`:'')),
  async(data,form)=>{
   data.vinculos=$$('.link-row',form).map(r=>({setor_id:Number($('[name="link-sector"]',r).value),cargo:$('[name="link-role"]',r).value,responsavel_id:Number($('[name="link-parent"]',r).value)||null}));
   delete data['link-sector'];delete data['link-role'];delete data['link-parent'];data.email=data.email||null;
   const result=await api('/usuarios/'+uid,'PUT',data);if(result.convite)setTimeout(()=>invitation(result.convite),20);
  });
 $('#link-list').dataset.row='';
 $('#modal-body').addLink=()=>$('#link-list').insertAdjacentHTML('beforeend',row({}));
}
function invitation(token) {modal('Convite de definição de senha',`<div class="notice info">Este código permite definir a senha da conta e expira em 72 horas. Entregue-o somente ao usuário, por um canal privado.</div><p>Use o fluxo de convite do sistema principal ou o comando documentado no README, que chama <code>POST /auth/definir-senha</code>.</p><div class="token">${esc(token)}</div><p class="help">O código é exibido apenas nesta operação. Não aparece no histórico.</p>`);}
function sectorModal(sid=0){
 const s=state.setores.find(s=>s.id===sid)||{nome:'',descricao:'',ativo:true,modulos:[],cargos:[]};
 modal(sid?'Editar setor':'Novo setor',confirmedForm(`${field('nome','Nome',s.nome,'text','required maxlength="100"')}<label>Descrição<textarea name="descricao" maxlength="500">${esc(s.descricao)}</textarea></label><div class="checklist">${check('ativo','Setor ativo',s.ativo)}</div><h3>Módulos existentes</h3><div class="checklist">${[...new Set(state.catalogo.map(k=>k.split(':')[0]))].map(m=>check('modulos',title(m),s.modulos.includes(m),m)).join('')}</div><h3>Cargos autorizados</h3><div class="checklist">${state.cargos.map(c=>check('cargos',title(c),s.cargos.includes(c),c)).join('')}</div><p class="help">Desativar o setor preserva usuários e histórico, mas nega as permissões desse contexto.</p>`),async(data,form)=>{const fd=new FormData(form);data.ativo=fd.has('ativo');data.modulos=fd.getAll('modulos');data.cargos=fd.getAll('cargos');await api('/setores/'+sid,'PUT',data);});
}
function limitModal(cargo='',sid=0){
 const l=state.limites.find(l=>l.cargo===cargo&&l.setor_id===sid)||{maximo:0,habilitado:false,alerta_percentual:80,pode_cadastrar:false};
 modal('Configurar limite',confirmedForm(`<div class="form-grid">${select('cargo','Cargo',state.cargos.map(c=>[c,title(c)]),cargo)}${select('setor_id','Contexto',[[0,'Empresa inteira'],...state.setores.map(s=>[s.id,s.nome])],sid)}${field('maximo','Máximo de usuários ativos',l.maximo,'number','required min="0" max="1000000"')}${field('alerta_percentual','Alertar ao atingir (%)',l.alerta_percentual,'number','required min="1" max="100"')}</div><div class="checklist">${check('habilitado','Liberar cadastros e reativações',l.habilitado)}${check('pode_cadastrar','Permitir delegação deste cargo (global)',l.pode_cadastrar)}</div><p class="help">Ativos e convites pendentes utilizam vagas. Reduzir o limite abaixo do uso atual bloqueia novas entradas sem desativar usuários.</p>`),async(data,form)=>{const c=data.cargo,s=Number(data.setor_id);delete data.cargo;delete data.setor_id;data.maximo=Number(data.maximo);data.alerta_percentual=Number(data.alerta_percentual);data.habilitado=new FormData(form).has('habilitado');data.pode_cadastrar=new FormData(form).has('pode_cadastrar');await api('/limites/'+c+'/'+s,'PUT',data);});
}
function permissionModal(){
 modal('Editar permissão',confirmedForm(`<div class="form-grid">${select('usuario_id','Aplicar a',[[0,'Padrão do cargo'],...state.usuarios.map(u=>[u.id,u.nome])],0)}${select('setor_id','Setor',state.setores.map(s=>[s.id,s.nome]))}${select('cargo','Cargo (para regra padrão)',state.cargos.map(c=>[c,title(c)]))}${select('permissao','Permissão existente',state.catalogo.map(k=>[k,k]))}${select('estado','Regra',[['herdar','Herdar / remover personalização'],['permitido','Permitido'],['negado','Negado']])}</div><div id="permission-current" class="notice info">Selecione o contexto para consultar a regra atual.</div><p class="help">“Herdar” remove a exceção individual. No padrão do cargo, remove a regra; o acesso passa a ser negado por padrão. Exceções não concedem setores adicionais.</p>`),async(data)=>{data.usuario_id=Number(data.usuario_id)||null;data.setor_id=Number(data.setor_id);await api('/permissoes','PUT',data);});
 const update=()=>{const f=$('#edit-form'),uid=Number($('[name=usuario_id]',f).value),sid=Number($('[name=setor_id]',f).value),cargo=$('[name=cargo]',f).value,key=$('[name=permissao]',f).value;const obj=uid?state.excecoes.find(e=>e.usuario_id===uid&&e.setor_id===sid&&e.permissao===key):state.regras.find(e=>e.cargo===cargo&&e.setor_id===sid&&e.permissao===key);$('#permission-current').textContent='Regra atual: '+(obj?(obj.permitido?'Permitido':'Negado'):'Herdar / sem regra explícita');$('[name=estado]',f).value=obj?(obj.permitido?'permitido':'negado'):'herdar';};
 $$('#edit-form select').forEach(s=>{if(s.name!=='estado')s.addEventListener('change',update);});update();
}
function critical(uid,action){modal(action==='senha'?'Iniciar redefinição de senha':'Encerrar sessões',confirmedForm(`<p>Usuário: <b>${esc(userName(uid))}</b></p><div class="notice">${action==='senha'?'O acesso ficará pendente até o usuário definir a própria senha. As sessões serão revogadas.':'Encerra as sessões do painel, revoga refresh tokens e invalida tokens de acesso emitidos pelo backend integrado.'}</div>`),async(data)=>{const result=await api('/usuarios/'+uid+'/'+action,'POST',data);if(result.convite)setTimeout(()=>invitation(result.convite),20);});}
document.addEventListener('click',async event=>{
 const button=event.target.closest('button[data-action],button[data-page]');if(!button)return;
 if(button.dataset.page && !button.closest('#navigation')) {currentPage=button.dataset.page;await render();return;}
 const action=button.dataset.action;if(!action)return;const uid=Number(button.dataset.id);
 try {
  if(action==='cancel')$('#modal').close();
  else if(action==='user-new')userModal();else if(action==='user-edit')userModal(uid);
  else if(action==='sector-new')sectorModal();else if(action==='sector-edit')sectorModal(uid);
  else if(action==='limit-new')limitModal();else if(action==='limit-edit')limitModal(button.dataset.cargo,Number(button.dataset.sid));
  else if(action==='permission-new')permissionModal();else if(action==='add-link')$('#modal-body').addLink();else if(action==='remove-link')button.closest('.link-row').remove();
  else if(action==='sessions')critical(uid,'sessoes');else if(action==='password')critical(uid,'senha');
  else if(action==='audit-detail'){const log=lastHistory.find(l=>l.id===uid);modal('Detalhes da atividade',`<p>${esc(log.acao)} · ${esc(new Date(log.criado_em).toLocaleString('pt-BR'))}</p><h3>Antes</h3><pre>${esc(JSON.stringify(log.antes,null,2)||'Sem valores anteriores')}</pre><h3>Depois e justificativa</h3><pre>${esc(JSON.stringify(log.depois,null,2)||'Sem valores posteriores')}</pre>`);}
  else if(action==='history-prev'){historyPage=Math.max(1,historyPage-1);await render();}else if(action==='history-next'){historyPage++;await render();}
  else if(action==='effective'){const result=await api('/permissoes/'+$('[name=effective-user]').value+'/'+$('[name=effective-sector]').value);$('#effective-result').innerHTML=table(['Permissão','Acesso','Origem'],result.map(r=>`<tr><td>${esc(r.permissao)}</td><td>${r.permitido?'Permitido':'Negado'}</td><td>${esc(r.origem)}</td></tr>`));}
 } catch(e){toast(e.message);}
});
(async()=>{try{await enter(await api('/session'));}catch(error){if(!error.message.includes('Entre com'))$('#login-error').textContent=error.message;}})();

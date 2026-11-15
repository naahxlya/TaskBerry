# 🍇 TaskBerry

### Gestão inteligente para pequenos negócios

O **TaskBerry** é um sistema web de gestão desenvolvido com o objetivo de simplificar a organização e o controle das atividades de pequenos negócios.

A proposta é reunir, em uma única plataforma, ferramentas para administrar clientes, funcionários, serviços, materiais, ferramentas e movimentações financeiras, oferecendo uma visão mais clara do funcionamento e da saúde financeira do negócio.

O projeto busca tornar a gestão empresarial mais acessível, organizada e eficiente, especialmente para pequenos empreendedores que precisam de controle sobre suas operações, mas não necessariamente dispõem de sistemas complexos ou de alto custo.

---

## 🎯 Objetivo do projeto

Desenvolver uma plataforma de gestão que centralize informações e facilite o acompanhamento das atividades administrativas e operacionais de pequenos negócios.

O TaskBerry pretende reduzir a dependência de controles manuais e informações espalhadas em diferentes ferramentas, proporcionando mais organização, praticidade e apoio à tomada de decisões.

## 💡 Funcionalidades

O sistema está sendo desenvolvido por módulos, permitindo que diferentes áreas do negócio sejam administradas de maneira integrada.

### 🔐 Autenticação e conta do usuário
- Cadastro de usuários.
- Login e logout.
- Recuperação e redefinição de senha.
- Gerenciamento de sessão.
- Perfil com informações do usuário e do negócio.

### 👥 Gestão de clientes
- Cadastro, edição, consulta e exclusão de clientes.
- Armazenamento de nome, telefone, e-mail e endereço.
- Registro de observações.
- Histórico e quantidade de serviços solicitados.
- Pesquisa de clientes cadastrados.

### 🛠️ Gestão de ferramentas e materiais
- Cadastro e controle de ferramentas.
- Identificação e localização dos equipamentos.
- Acompanhamento do estado de conservação.
- Registro de manutenções.
- Controle de materiais disponíveis.
- Acompanhamento de compras e utilização de materiais nos serviços.

### 🏗️ Gestão de obras e chamados
- Cadastro de serviços e chamados.
- Associação de cada serviço a um cliente.
- Registro do valor de cada trabalho.
- Acompanhamento do andamento dos serviços.
- Identificação de serviços iniciados, pendentes ou atrasados.
- Controle dos materiais utilizados em cada trabalho.

### 👨‍💼 Gestão de funcionários
- Cadastro e gerenciamento de funcionários.
- Controle de salários e pagamentos.
- Registro de adiantamentos.
- Controle de horas extras e descontos.
- Acompanhamento de benefícios, como vale-transporte e vale-refeição.
- Campo para observações e informações administrativas.

### 💰 Gestão financeira (ERP)
- Registro de entradas e saídas financeiras.
- Controle de valores recebidos e pagamentos pendentes.
- Associação de movimentações a clientes e funcionários.
- Registro de despesas com materiais e manutenção.
- Acompanhamento de custos operacionais.
- Cálculo de resultados, lucros e prejuízos.
- Visão geral da situação financeira do negócio.

### 📊 Relatórios e indicadores
- Resumo das movimentações financeiras.
- Acompanhamento de receitas e despesas.
- Indicadores de desempenho do negócio.
- Informações sobre clientes e serviços.
- Relatórios para auxiliar no planejamento e na tomada de decisões.

> As funcionalidades descritas representam a proposta completa do TaskBerry. Algumas estão em desenvolvimento e serão disponibilizadas gradualmente conforme a evolução do projeto.

---

## 🧰 Tecnologias utilizadas

O TaskBerry utiliza tecnologias voltadas ao desenvolvimento web, organização de dados e construção de interfaces responsivas.

| Tecnologia | Aplicação |
|---|---|
| Python | Linguagem principal do backend |
| Flask | Framework para desenvolvimento web |
| MongoDB | Banco de dados NoSQL |
| PyMongo | Integração entre Python e MongoDB |
| HTML5 | Estrutura das páginas |
| CSS3 | Estilização das interfaces |
| JavaScript | Interatividade no frontend |
| Bootstrap 5 | Componentes e responsividade |
| Bootstrap Icons | Ícones da interface |
| Jinja2 | Renderização dinâmica de páginas |
| Git e GitHub | Versionamento e gerenciamento do código |

---

## 🏛️ Arquitetura do projeto

O sistema utiliza uma organização modular, separando as responsabilidades de rotas, conexão com o banco de dados, templates e arquivos estáticos.

```text
TaskBerry/
│
├── app/
│   ├── __init__.py
│   │
│   ├── database/
│   │   └── connection.py
│   │
│   ├── routes/
│   │   ├── auth.py
│   │   ├── dashboard.py
│   │   ├── perfil.py
│   │   └── clientes.py
│   │
│   ├── templates/
│   │   ├── index.html
│   │   ├── login.html
│   │   ├── cadastro.html
│   │   ├── recuperar_senha.html
│   │   ├── redefinir_senha.html
│   │   ├── dashboard.html
│   │   ├── perfil.html
│   │   └── clientes.html
│   │
│   └── static/
│       ├── css/
│       │   └── style.css
│       │
│       ├── js/
│       │   └── script.js
│       │
│       └── img/
│
├── .env
├── .env.example
├── .gitignore
├── requirements.txt
└── run.py
```

A estrutura poderá receber novos módulos conforme o desenvolvimento das funcionalidades.

---

## 🔒 Segurança e organização dos dados

O TaskBerry considera a proteção das informações um aspecto importante do desenvolvimento.

Entre os cuidados previstos para o sistema estão:

- Autenticação de usuários.
- Controle de acesso às páginas internas.
- Separação dos dados de acordo com o usuário autenticado.
- Proteção de credenciais por meio de variáveis de ambiente.
- Validação das informações enviadas pelos formulários.
- Restrição de acesso a registros pertencentes a outros usuários.

A segurança será aprimorada continuamente conforme novos módulos forem implementados.

---

## 🚀 Etapas de desenvolvimento

O projeto está sendo desenvolvido de forma incremental, com implementação e validação de cada módulo.

- [x] Estrutura inicial da aplicação Flask.
- [x] Configuração da conexão com MongoDB.
- [x] Cadastro e autenticação de usuários.
- [x] Estrutura de recuperação de senha.
- [x] Dashboard inicial.
- [x] Gerenciamento de perfil.
- [x] Cadastro, edição, consulta e exclusão de clientes.
- [ ] Gestão de ferramentas e materiais.
- [ ] Gestão de obras e chamados.
- [ ] Gestão de funcionários.
- [ ] Implementação completa do módulo financeiro (ERP).
- [ ] Relatórios e indicadores gerenciais.
- [ ] Testes e melhorias de segurança.
- [ ] Implantação da versão final.

---

## 🌱 Visão futura

Mais do que organizar cadastros, o TaskBerry pretende oferecer uma visão integrada do negócio.

A proposta é permitir que o empreendedor acompanhe desde o primeiro contato com um cliente até a execução do serviço, os materiais utilizados, os custos envolvidos e o resultado financeiro obtido.

Com isso, o sistema poderá contribuir para uma gestão mais consciente, baseada em informações organizadas e indicadores que auxiliem nas decisões do dia a dia.

## 👩‍💻 Desenvolvimento

O TaskBerry é um projeto acadêmico desenvolvido como parte da formação em Análise e Desenvolvimento de Sistemas, com foco em desenvolvimento web, banco de dados, organização de processos e aplicação de tecnologia na gestão empresarial.

**Desenvolvimento:** Nathalya Victoria Vieira.

---

<p align="center">
  🍇 <strong>TaskBerry</strong><br>
  Gestão mais simples, negócios mais organizados.
</p>
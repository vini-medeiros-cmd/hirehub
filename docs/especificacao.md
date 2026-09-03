HireHub — Especificação Consolidada
1. Conceito

HireHub é um agregador público e gratuito de oportunidades de emprego.

O sistema coleta vagas de diferentes plataformas de recrutamento, normaliza e organiza os dados em uma base própria e disponibiliza tudo em uma única interface.

Slogan

O hub das oportunidades, seu próximo emprego começa aqui.

Princípios
🌐 Público e aberto
🚫 Sem cadastro
🚫 Sem login
🚫 Sem favoritos
🚫 Sem candidatura dentro do HireHub
🔎 Busca rápida
🎯 Filtros objetivos
🔗 Candidatura diretamente na plataforma de origem
🔄 Atualização automática a cada 6 horas
📱 Interface responsiva
⚡ Carregamento rápido

3. Infraestrutura

O HireHub será hospedado em uma VPS gratuita da Oracle Cloud.

Atualização automática

A coleta será executada a cada 6 horas:

00:00 → Coleta
06:00 → Coleta
12:00 → Coleta
18:00 → Coleta

4. Fontes de vagas
MVP
InHire
Gupy
Sólides
InfoJobs
Futuro

A arquitetura deve permitir adicionar novas fontes sem precisar modificar o núcleo do sistema.

Cada fonte deve funcionar como um conector independente.

5. Interface

A interface deve transmitir:

Profissional + moderna + limpa + objetiva

Direção visual

Inspirada conceitualmente em:

LinkedIn + Indeed + SaaS moderno

Mas sem copiar a identidade visual dessas plataformas.

Características
Fundo predominantemente branco
Bastante espaço negativo
Cantos quadrados
Cards limpos
Tipografia forte nos títulos
Poucos elementos decorativos
Hierarquia visual clara
Poucos efeitos
Sem excesso de gradientes
Sem excesso de verde
Sem sombras pesadas
Importante

Você definiu cantos quadrados como característica do HireHub.

Portanto, a interface não deve seguir a tendência de deixar absolutamente tudo excessivamente arredondado.

Sugestão:

Cards: 2–4px
Inputs: 2–4px
Botões: 2–4px
Badges: podem continuar levemente arredondados para diferenciá-los visualmente.

6. Identidade visual
Cores
Cor	Hex	Uso
Verde	#1DB954	CTA, sucesso, Nova Vaga
Azul	#0A66C2	Links, menus, informações
Branco	#FFFFFF	Fundo e cards
Preto	#0F0F0F	Títulos e textos principais
Tipografia

Títulos: Poppins
Corpo: Open Sans

Hierarquia de cores

Azul → navegação e informação

Verde → ação e conversão

Preto → conteúdo

7. Header

O cabeçalho deve ser simples.

Esquerda

Logo HireHub

Direita
Início
Vagas
Sobre
Contato

E, se fizer sentido:

Redes sociais

Não haverá:

Login
Cadastro
Área do candidato
Perfil

8. Data e hora atual

O HireHub deverá apresentar a data e hora atual de forma discreta.

Exemplo:

03/09/2026 · 09:32

Pode ficar no header ou em uma área secundária.

Isso também reforça a percepção de que o portal é um sistema ativo e constantemente atualizado.

9. Busca

A busca será o elemento central da página.

Campos

Palavra-chave

🔎 Cargo, tecnologia ou palavra-chave

Localização

📍 Cidade, estado ou região
Botão
[ BUSCAR VAGAS ]

Exemplos:

Desenvolvedor Python
Analista de TI
Suporte Técnico
Engenheiro de Software
Power BI
Macaé
Rio das Ostras
Rio de Janeiro

10. Filtros
Data de publicação
Últimas 24 horas
Última semana
Último mês
Qualquer momento
Modalidade
Remoto
Híbrido
Presencial
Qualquer modalidade
Plataforma
InHire
Gupy
Sólides
InfoJobs
Todas

11. Listagem

Antes dos cards:

Contador

1.248 vagas encontradas

Atualização

Última atualização: 03/09/2026 às 06:00

Ou:

Atualizado há 3 horas · Próxima atualização em aproximadamente 3 horas

O contador deve ser calculado com base nos dados efetivamente existentes no banco.

12. Cards de vagas

Desktop:

2 cards lado a lado.

┌───────────────────────────────────┐
│ NOVA                              │
│                                   │
│ Analista de Sistemas              │
│                                   │
│ Empresa XYZ                       │
│ Macaé, RJ                         │
│ Híbrido                           │
│                                   │
│ Gupy                              │
│ Publicada há 4 horas              │
│                                   │
│             [ Candidatar-se ]     │
└───────────────────────────────────┘

Mobile:

1 card por linha.

13. Informações do card

Cada card terá:

Obrigatórias
Nome da vaga
Empresa
Local
Modalidade
Plataforma de origem
Data de publicação
Botão Candidatar-se
Opcional
Salário
Badge NOVA

14. Badge "NOVA"

Uma vaga será considerada:

NOVA = publicada nas últimas 24 horas

Visual:

🟢 NOVA

Cor:

#1DB954

5. Botão Candidatar-se

O CTA principal do HireHub.

Visual
Fundo: #1DB954
Texto: #FFFFFF
Cantos quadrados
Alto contraste
Destaque visual
Fluxo
Usuário
   ↓
HireHub
   ↓
"Candidatar-se"
   ↓
URL original
   ↓
Gupy / Sólides / InHire / InfoJobs
   ↓
Candidatura

O HireHub não realiza a candidatura.

Também não precisa armazenar:

currículo;
nome;
e-mail;
telefone;
documentos;
informações da candidatura.

Isso mantém o produto extremamente simples.

16. Página de detalhes

Ao clicar na vaga:

← Voltar para vagas

Analista de Sistemas

Empresa XYZ

📍 Macaé, RJ
💼 Híbrido
🔵 Gupy
📅 Publicada em 03/09/2026

────────────────────────

Descrição da vaga

...

────────────────────────

Requisitos

...

────────────────────────

Benefícios

...

────────────────────────

Salário

R$ X.XXX – R$ X.XXX

[ CANDIDATAR-SE ]

O botão continua levando para a URL original da vaga.

17. Status das fontes

O HireHub deve mostrar que as informações são atualizadas automaticamente.

Exemplo:

Fontes
● InHire       Atualizado
● Gupy         Atualizado
● Sólides      Atualizado
● InfoJobs     Atualizado

Podemos transformar isso futuramente em uma página:

/status

com:

HireHub — Status das integrações

InHire
✓ Operacional
Última coleta: 06:02

Gupy
✓ Operacional
Última coleta: 06:04

Sólides
✓ Operacional
Última coleta: 06:08

InfoJobs
✓ Operacional
Última coleta: 06:11

18. Sobre

O site terá uma página Sobre o HireHub.

Conteúdo sugerido:

O que é o HireHub?

O HireHub é um agregador de oportunidades que reúne vagas de diferentes plataformas de emprego em um único lugar.

O objetivo é tornar a busca por oportunidades mais simples, rápida e centralizada.

Como funciona?
Plataformas
     ↓
HireHub coleta
     ↓
Organiza e normaliza
     ↓
Disponibiliza as vagas
     ↓
Você encontra uma oportunidade
     ↓
Candidata-se na plataforma original
Importante

O HireHub não é responsável pelo processo seletivo.

As candidaturas são realizadas diretamente nas plataformas ou sites responsáveis pela publicação da vaga.

19. Contato

Terá uma seção/página:

Entre em contato

Com opções como:

E-mail
LinkedIn
GitHub
Outras redes sociais

Isso também transforma o HireHub em uma espécie de projeto/portfólio público, além de ser uma ferramenta útil.

20. Redes sociais

No footer:

HireHub

O hub das oportunidades,
seu próximo emprego começa aqui.

────────────────────────

Início
Vagas
Sobre
Contato

────────────────────────

LinkedIn
GitHub
Instagram
[ou outras redes]

────────────────────────

© 2026 HireHub

As redes sociais podem apontar para os seus perfis.

21. Footer

O rodapé deve ser escuro:

#0F0F0F

Com texto claro.

Estrutura:

┌─────────────────────────────────────────────────────┐
│ HireHub                                             │
│                                                     │
│ O hub das oportunidades,                            │
│ seu próximo emprego começa aqui.                   │
│                                                     │
│ Vagas     Sobre     Contato                         │
│                                                     │
│ LinkedIn   GitHub   Redes sociais                   │
│                                                     │
│ ─────────────────────────────────────────────────── │
│ © 2026 HireHub                                      │
└─────────────────────────────────────────────────────┘

24. Arquitetura geral

A visão final fica:

                    ┌─────────────┐
                    │   Gupy      │
                    ├─────────────┤
                    │  Sólides    │
                    ├─────────────┤
                    │   InHire    │
                    ├─────────────┤
                    │  InfoJobs   │
                    └──────┬──────┘
                           │
                           ▼
                 ┌──────────────────┐
                 │     Backend      │
                 │                  │
                 │ Coletores        │
                 │ Normalização     │
                 │ Validação        │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │    Database      │
                 │                  │
                 │ Vagas processadas│
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │     API          │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │    Frontend      │
                 │    HireHub       │
                 └────────┬─────────┘
                          │
                          ▼
                       Usuário
                          │
                          ▼
                 Candidatura externa

25. MVP final
🔎 Busca
Palavra-chave
Localização
🎯 Filtros
Data
Modalidade
Plataforma
📋 Vagas
Lista
Cards
Página de detalhes
Contador
Data de publicação
Plataforma
Modalidade
Localização
🔗 Candidatura
Link externo para a vaga original
🔄 Atualização
Automática
A cada 6 horas
Status das fontes
Última sincronização
🌐 Institucional
Sobre
Contato
Redes sociais
Data/hora atual
🚫 Fora do MVP
Login
Cadastro
Favoritos
Perfil
Currículo
Candidatura interna
Chat
Sistema de mensagens
Rede social
Área do candidato

26. Essência do HireHub

O produto pode ser resumido em:

🔎 Encontrar → 📋 Entender → 🔗 Candidatar-se

E tecnicamente:

Coletar → Normalizar → Armazenar → Exibir → Redirecionar

Acho que essa versão deixa o escopo bem fechado para começar o desenvolvimento, sem adicionar funcionalidades que desviem da proposta principal.

Ponto-chave: o HireHub não precisa ser um sistema complexo para o usuário. A complexidade fica nos bastidores, na coleta, normalização, deduplicação e atualização das vagas. Para quem acessa, a experiência deve parecer simplesmente: entrei → pesquisei → encontrei → cliquei → candidatei-me.

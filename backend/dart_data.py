"""Dados de configuração do DART — Avaliação de Perfil Comportamental.

As perguntas ficam aqui apenas como seed inicial (inseridas na tabela
`dart_perguntas`/`dart_alternativas` de forma idempotente). A partir daí o
questionário pode ser administrado/editado via banco, permitindo gerar novas
versões do teste sem reescrever a aplicação.
"""

DART_PERFIS = ["analista", "executor", "comunicador", "planejador"]

DART_PERFIS_ROTULO = {
    "analista": "Analista",
    "executor": "Executor",
    "comunicador": "Comunicador",
    "planejador": "Planejador",
}

# Codenomes configuráveis (mapeiam combinações ordenadas de perfis -> nome).
# A regra de corte que decide quais perfis entram na combinação é configurável
# e deve ser definida posteriormente; não implementamos ainda uma regra fixa.
DART_CODENAMES = {
    "analista": "O Investigador",
    "executor": "O Realizador",
    "comunicador": "O Influenciador",
    "planejador": "O Estrategista",
    "analista+executor": "O Solucionador",
    "analista+comunicador": "O Especialista",
    "analista+planejador": "O Arquiteto",
    "executor+comunicador": "O Líder",
    "executor+planejador": "O Gestor",
    "comunicador+planejador": "O Articulador",
    "analista+executor+comunicador": "O Catalisador",
    "analista+executor+planejador": "O Estrategista de Resultados",
    "analista+comunicador+planejador": "O Consultor",
    "executor+comunicador+planejador": "O Líder Mobilizador",
    "analista+executor+comunicador+planejador": "O Visionário",
}

# 25 questões situacionais. Cada alternativa é associada a um perfil.
# A ordem das alternativas é embaralhada por pergunta no seed (ordem variada),
# para o perfil não ficar sempre na mesma posição.
DART_QUESTIONS_V1 = [
    {
        "texto": "Você recebeu um projeto importante, mas as informações ainda estão incompletas. O que você tende a fazer primeiro?",
        "alternativas": {
            "analista": "Procuro entender os dados disponíveis, identificar o que está faltando e avaliar possíveis problemas.",
            "executor": "Começo a executar o que já pode ser feito e resolvo as pendências conforme aparecem.",
            "planejador": "Organizo as informações, defino etapas e estabeleço o que precisa ser resolvido antes de começar.",
            "comunicador": "Converso com as pessoas envolvidas para entender diferentes perspectivas e alinhar expectativas.",
        },
    },
    {
        "texto": "Sua equipe está com um desafio novo e ninguém sabe por onde começar. Qual é sua reação natural?",
        "alternativas": {
            "executor": "Proponho começar por alguma coisa e ajustar o rumo enquanto agimos.",
            "analista": "Estudo o desafio, levanto dados e apresento uma leitura clara da situação.",
            "comunicador": "Reúno a equipe, estimulo a troca de ideias e uns aos outros.",
            "planejador": "Estruturo um roteiro com etapas e prazos antes de qualquer movimento.",
        },
    },
    {
        "texto": "Você precisa convencer um grupo a apoiar uma ideia sua. Como age?",
        "alternativas": {
            "comunicador": "Falo com as pessoas individualmente, mostro os benefícios e crio conexão.",
            "analista": "Apresento os fatos, números e uma argumentação lógica e objetiva.",
            "executor": "Mostro na prática como a ideia funciona com um exemplo real e rápido.",
            "planejador": "Preparo um plano detalhado com prazos e resultados esperados para apresentar.",
        },
    },
    {
        "texto": "Você descobriu que algo importante vai dar errado se ninguém agir. Qual é seu primeiro impulso?",
        "alternativas": {
            "executor": "Vou direto corrigir o que dá para corrigir agora.",
            "analista": "Analiso a origem do problema e as consequências possíveis.",
            "planejador": "Mapeio um plano de contingência com passos e prioridades.",
            "comunicador": "Aviso as pessoas envolvidas e combino uma ação conjunta.",
        },
    },
    {
        "texto": "Ao chegar a um ambiente novo de trabalho, o que mais chama sua atenção?",
        "alternativas": {
            "analista": "Como as coisas funcionam, quais processos existem e o que pode falhar.",
            "comunicador": "As pessoas, quem são e como posso me relacionar com elas.",
            "executor": "O que precisa ser feito hoje e que resultado posso entregar já.",
            "planejador": "Como o trabalho está organizado e que rotinas o futuro exigirá.",
        },
    },
    {
        "texto": "Quando alguém discorda de você, qual é seu comportamento mais comum?",
        "alternativas": {
            "analista": "Ouço o ponto, comparo com os fatos e respondo com lógica.",
            "comunicador": "Tento entender a perspectiva do outro e manter a relação em paz.",
            "planejador": "Reavalio o plano considerando o que foi levantado e ajusto a ordem.",
            "executor": "Defendo minha posição e proponho uma solução prática para avançarmos.",
        },
    },
    {
        "texto": "Você precisa entregar uma tarefa em um prazo apertado. O que faz?",
        "alternativas": {
            "executor": "Monto um cronograma curto e coloco a mão na massa imediatamente.",
            "planejador": "Priorizo o essencial, divido em partes e defino o que fazer primeiro.",
            "analista": "Verifico exatamente o que é exigido para não errar na entrega.",
            "comunicador": "Peço ajuda a quem pode acelerar e alinho as expectativas das partes.",
        },
    },
    {
        "texto": "Um colega está claramente insatisfeito, mas não diz o motivo. O que você percebe primeiro?",
        "alternativas": {
            "comunicador": "O desconforto da pessoa e a vontade de abrir um diálogo.",
            "analista": "Sinais de que algo no processo ou no resultado mudou.",
            "planejador": "Que a rotina ou as expectativas não estão alinhadas como deveriam.",
            "executor": "Que algo precisa ser resolvido para ele voltar a trabalhar bem.",
        },
    },
    {
        "texto": "Você ganhou mais responsabilidades. O que você faz espontaneamente?",
        "alternativas": {
            "planejador": "Faço um planejamento do que vai exigir e como vou me organizar.",
            "executor": "Aceito e começo a agir para dominar o novo desafio rapidamente.",
            "analista": "Busco entender a fundo a nova área e os critérios de sucesso.",
            "comunicador": "Procuro me alinhar com as pessoas e criar bons contatos de apoio.",
        },
    },
    {
        "texto": "Sua empresa quer entrar em um mercado totalmente novo. Qual sua maior contribuição?",
        "alternativas": {
            "analista": "Pesquisar o mercado, analisar concorrentes e riscos com profundidade.",
            "comunicador": "Apresentar a ideia, engajar o time e conquistar parceiros.",
            "planejador": "Desenhar o plano de entrada com etapas, metas e prazos.",
            "executor": "Montar a operação e fazer a primeira venda acontecer o quanto antes.",
        },
    },
    {
        "texto": "Em uma reunião com muitas opiniões, o que você mais faz?",
        "alternativas": {
            "planejador": "Conduzo para um encaminhamento organizado e com próximos passos.",
            "analista": "Resumo o que foi dito e aponto o que faz sentido ou não.",
            "comunicador": "Dou voz às pessoas e busco um consenso agradável.",
            "executor": "Trago a conversa para o que dá para decidir e executar já.",
        },
    },
    {
        "texto": "Você recebe uma crítica no trabalho. Como reage na maioria das vezes?",
        "alternativas": {
            "analista": "Avalio se a crítica procede e o que posso melhorar com dados.",
            "planejador": "Reflito sobre como ajustar meu modo de trabalhar para evitar repetir.",
            "comunicador": "Agradeço, converso sobre o ponto e preservo o bom relacionamento.",
            "executor": "Assumo e me empenho em corrigir na prática sem enrolação.",
        },
    },
    {
        "texto": "Você tem uma folga no fim de semana. O que prefere fazer no tempo livre?",
        "alternativas": {
            "executor": "Atividades dinâmicas, esportes ou tarefas práticas e com resultado.",
            "comunicador": "Estar com pessoas, conversar e aproveitar a companhia de outros.",
            "analista": "Estudar algo novo, ler ou aprofundar um tema de interesse.",
            "planejador": "Organizar a semana, planejar compromissos e colocar a vida em ordem.",
        },
    },
    {
        "texto": "Um objetivo grande parece muito distante. Qual é sua atitude típica?",
        "alternativas": {
            "planejador": "Divido em metas menores e crio um caminho passo a passo.",
            "executor": "Começo a trabalhar nele de imediato, mesmo que aos poucos.",
            "analista": "Monto um panorama realista do que é necessário para alcançá-lo.",
            "comunicador": "Busco apoio de pessoas para caminhar junto e me manter motivado.",
        },
    },
    {
        "texto": "Quando você precisa aprender algo totalmente novo, como aborda?",
        "alternativas": {
            "analista": "Estudo a teoria, os conceitos e as referências antes de usar.",
            "executor": "Vou tentando na prática e aprendo fazendo.",
            "planejador": "Defino o que preciso dominar e organizo um cronograma de estudo.",
            "comunicador": "Pergunto a quem já domina e aprendo com a troca e exemplos.",
        },
    },
    {
        "texto": "A empresa pediu ideias para melhorar um processo. O que você propõe?",
        "alternativas": {
            "analista": "Um diagnóstico do que está causando gargalos, com base em dados.",
            "planejador": "Um redesenho do fluxo, documentando etapas e responsáveis.",
            "executor": "Uma mudança simples e rápida que já gera melhoria hoje.",
            "comunicador": "Uma rodada de conversas com quem usa o processo para ouvir sugestões.",
        },
    },
    {
        "texto": "Seu time está em conflito por um problema urgente. Qual seu papel mais natural?",
        "alternativas": {
            "comunicador": "Mediar a conversa, acalmar os ânimos e buscar acordo.",
            "executor": "Cortar o problema pela raiz com uma atitude objetiva.",
            "analista": "Expor os fatos do problema para tirar o conflito do campo emocional.",
            "planejador": "Propor um encaminhamento estruturado para resolver sem novos atritos.",
        },
    },
    {
        "texto": "Você precisa tomar uma decisão sem ter todas as informações. O que faz?",
        "alternativas": {
            "analista": "Levanto o máximo de dados possíveis e decido de forma fundamentada.",
            "executor": "Decido com base no que tenho e corrijo o rumo se preciso.",
            "planejador": "Avalio os cenários e escolho a opção com melhor relação entre risco e plano B.",
            "comunicador": "Consulto pessoas de confiança e decido considerando o grupo.",
        },
    },
    {
        "texto": "O que mais te incomoda em um ambiente de trabalho?",
        "alternativas": {
            "planejador": "Falta de organização, metas confusas e improviso constante.",
            "executor": "Lentidão, burocracia e a sensação de que nada anda.",
            "analista": "Desperdício, decisões sem embasamento e erros evitáveis.",
            "comunicador": "Clima ruim, falta de comunicação e pessoas distantes.",
        },
    },
    {
        "texto": "Você conquistou um resultado importante. O que mais te motiva nessa conquista?",
        "alternativas": {
            "executor": "Ver o resultado acontecer e saber que cheguei lá.",
            "planejador": "Confirmar que o planejamento funcionou como previsto.",
            "comunicador": "Compartilhar a conquista e o reconhecimento com as pessoas.",
            "analista": "Entender o que funcionou para repetir o sucesso com mais precisão.",
        },
    },
    {
        "texto": "Surgiu uma oportunidade de mudar completamente sua área de atuação. Como decide?",
        "alternativas": {
            "analista": "Avalio prós e contras, o mercado e as chances de dar certo.",
            "executor": "Se fizer sentido na prática, toco em frente sem hesitar muito.",
            "planejador": "Traço um plano de transição considerando a carreira a longo prazo.",
            "comunicador": "Converso com pessoas que já passaram por algo parecido e me inspiro.",
        },
    },
    {
        "texto": "Durante uma crise, qual parte você assume com mais naturalidade?",
        "alternativas": {
            "executor": "Ação imediata: estabilizar a situação e resolver o urgente.",
            "planejador": "Organizar o time, priorizar tarefas e definir quem faz o quê.",
            "analista": "Entender a origem do problema e calcular os impactos.",
            "comunicador": "Tranquilizar o grupo, dar notícias claras e manter todos alinhados.",
        },
    },
    {
        "texto": "Como você costuma se preparar para uma apresentação importante?",
        "alternativas": {
            "planejador": "Estruturei bem o roteiro e ensaiei os pontos principais.",
            "analista": "Pesquisei e reuni fatos que sustentam cada afirmação.",
            "comunicador": "Pensei em como conectar com quem vai assistir e criar envolvimento.",
            "executor": "Preparei o essencial e conto com o improviso para os detalhes.",
        },
    },
    {
        "texto": "Um cliente importante está frustrado com o serviço. Qual é sua abordagem?",
        "alternativas": {
            "comunicador": "Ouvir com atenção, acolher o cliente e reconstruir a confiança.",
            "executor": "Resolver o problema do cliente de forma rápida e efetiva.",
            "analista": "Diagnosticar a causa raiz para que não volte a acontecer.",
            "planejador": "Definir um plano de correção com prazos e acompanhamento.",
        },
    },
    {
        "texto": "Se você pudesse descrever seu jeito de trabalhar, diria que você é, acima de tudo:",
        "alternativas": {
            "analista": "Criterioso e detalhista; prefiro fundamentar antes de concluir.",
            "executor": "Dinâmico e objetivo; gosto de entregar e seguir em frente.",
            "planejador": "Organizado e estratégico; penso antes de agir com método.",
            "comunicador": "Sociável e envolvente; valorizo as pessoas e o diálogo.",
        },
    },
]

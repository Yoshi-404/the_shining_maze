[README.txt](https://github.com/user-attachments/files/28978153/README.txt)


1. DESCRIÇÃO DO PROJETO E MOTIVAÇÃO
O projeto é um "Simulador de Sinuca de Boteco em 3D". O cenário é composto por uma mesa detalhada (com feltro, bordas de madeira e caçapas), um chão xadrez texturizado e bolas de sinuca sob o modelo de iluminação de Phong. O projeto inclui física de colisões e rolamento (com spin), sistema de partículas (pó de giz) e áudio espacial.
A escolha deste tema tem um valor tem como propósito a melhoria do projeto de quando realizei a disciplina de Computação Gráfica durante os meus estudos no Japão, o meu projeto final também foi um jogo de sinuca. No entanto, era uma versão bem inicial e mal acabada (não possuía caçapas modeladas direito e usava apenas câmera ortogonal, embora já tivesse o sistema de rotação das bolas e algumas texturas). 
Este projeto atual é a "versão definitiva e melhorada" daquele trabalho, demonstrando a minha evolução. Agora aplico conceitos avançados como caçapas embutidas com ilusão de profundidade (Z-buffer), câmera em perspectiva dinâmica interativa, interface HUD (para aplicar efeitos na bola), iluminação e texturização com Mipmapping (para evitar aliasing/moiré).


2. LINGUAGEM E BIBLIOTECAS USADAS
  - Python 
  - Pygame: Utilizado para a criação da janela, gerenciamento do loop principal, captura de eventos (mouse e teclado) e sistema de reprodução de áudio.
  - PyOpenGL (GL, GLU, GLUT): Utilizado para todo o pipeline de renderização gráfica 3D, geração de primitivas, mapeamento de texturas esféricas (Quadrics) e projeções matemáticas.


3. INSTRUÇÕES DE COMPILAÇÃO E EXECUÇÃO
  1. Certifique-se de ter o Python 3 instalado no sistema.
  2. Instale as bibliotecas necessárias através do terminal: pip install pygame PyOpenGL PyOpenGL_accelerate
  3. O diretório do projeto deve conter o arquivo 'main.py' junto com todos os arquivos de mídia auxiliares (as texturas .jpg da mesa e das bolas, e os arquivos de áudio .wav e .mp3).
  4. Para rodar, basta executar o comando no terminal dentro da pasta: python main.py


4. CONTROLES DE INTERAÇÃO (MOUSE E TECLADO)
  - Mouse (Botão Esquerdo): Clique no espaço da mesa e arraste para trás para mirar (a linha indica a força e direção). Solte para dar a tacada.
  - Mouse (Movimento Livre): Move a câmera ao redor da mesa para visualizar o jogo por diferentes ângulos.
  - Scroll do Mouse (Roda): Aproxima (Zoom In) e Afasta (Zoom Out) a câmera.
  - HUD (Canto Superior Direito): Clique e arraste o ponto vermelho para aplicar efeito (Spin / English) na bola branca.
  - Teclado [ P ]: Pausa e Despausa a partida em andamento.
  - Teclado [ R ]: Reinicia a mesa (reagrupa as bolas no triângulo e zera a pontuação).


5. JUSTIFICATIVA DA ESCOLHA DA PROJEÇÃO
Este projeto faz o uso híbrido e estratégico de duas projeções matemáticas diferentes, dependendo do elemento a ser renderizado:

Projeção em Perspectiva (gluPerspective): Escolhida para renderizar o mundo 3D principal (a mesa, as bolas e o chão). Ao contrário do meu projeto antigo feito no Japão (que usava ortogonal e deixava a mesa achatada), a perspectiva é essencial em um jogo de sinuca moderno para garantir o "foreshortening" (encurtamento visual). Isso permite ao jogador ter a noção real de profundidade e distância na hora de calcular a mira e a força da tacada.

Projeção Ortográfica (gluOrtho2D): Utilizada cirurgicamente apenas para a camada de interface de utilizador (como o painel de efeito HUD, os textos de pontuação e a tela de Pause/Game Over). Menus bidimensionais devem permanecer fixos na tela, imunes à distorção de profundidade, independente de onde a câmera 3D esteja apontando.

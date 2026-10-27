# Editor de Áudio CPK

Programa para substituir falas dentro de `dt510_bra_mobile_all.cpk`, com interface em português. Abre o CPK original, converte seus áudios para HCA e reconstrói um novo CPK. O original nunca é sobrescrito.

## Download para Windows

**[Baixar para Windows 10/11 de 64 bits (ZIP)](https://github.com/L650111/Editor-de-narra-ao-efootball-moblie/releases/latest/download/EditorCPKAudio-Windows-x64.zip)** · **[Baixar somente o EXE](https://github.com/L650111/Editor-de-narra-ao-efootball-moblie/releases/latest/download/EditorCPKAudio.exe)** · [Todas as versões](https://github.com/L650111/Editor-de-narra-ao-efootball-moblie/releases)

Extraia o ZIP e abra **EditorCPKAudio.exe**. Não precisa instalar Python, CriCodecs ou FFmpeg. O CPK original e os áudios do jogo não acompanham o programa. O ZIP também contém as instruções, licenças e o relatório de verificação do executável.

## Novidade na versão 1.2: escolher um áudio para repetir

Use **Repetir áudio** para colocar uma gravação escolhida por você em todas as falas do CPK ou somente nas falas do grupo atual.

1. Abra o CPK e clique em **Repetir áudio**, na área de Substituições.
2. Clique em **Escolher áudio** e selecione seu WAV, MP3 ou outro formato aceito.
3. Em **Aplicar em**, escolha **Todo o CPK (54.833 áudios)** ou o grupo selecionado.
4. Escolha **Manter a duração original** para cortar/completar com silêncio em cada posição, ou **Usar a duração do novo áudio** para manter a gravação inteira em todas as posições.
5. Clique em **Aplicar à lista**. As associações do escopo escolhido serão substituídas pelo arquivo selecionado.
6. Confira o contador, escolha um destino novo e clique em **Gerar novo CPK**.

O programa reaproveita a conversão do mesmo arquivo quando o perfil e a duração permitem. Manter as diferentes durações originais pode exigir mais codificações. Repetir uma gravação longa em milhares de posições também pode produzir um CPK muito grande; para um teste rápido, escolha um trecho curto.

Você pode trocar uma associação individual depois de aplicar o áudio em massa. O botão **Limpar** remove todas as associações da lista após confirmação. A lista completa pode ser salva em JSON para continuar depois.

## Novidade na versão 1.1: grupos iguais aos ZIPs

O seletor **Grupo de áudios e falas** agora usa as mesmas divisões dos ZIPs exportados anteriormente. A busca e a importação de pasta atuam no grupo selecionado. A lista de substituições também mostra o grupo de cada áudio.

| Grupo / nome do ZIP | Áudios | IDs originais |
|---|---:|---|
| `00_TEAM.zip` | 3.976 | 0–3975 |
| `10_PLAYER_1.zip` | 1.074 | 0–1073 |
| `10_PLAYER_2.zip` | 15.585 | 1074–16658 |
| `10_PLAYER_3.zip` | 20.551 | 16659–37209 |
| `10_PLAYER_4.zip` | 3.966 | 37210–41175 |
| `20_MAIN_1.zip` | 5.352 | 0–5351 |
| `20_MAIN_2.zip` | 782 | 5352–6133 |
| `30_MAIN.zip` | 3.269 | 0–3268 |
| `40_MAIN.zip` | 278 | 0–277 |

As partes organizam a navegação e a exportação; na montagem do CPK, cada áudio continua associado ao banco e ID corretos do jogo.

## Exportar os grupos em ZIPs

1. Abra o CPK e clique em **Exportar ZIPs**, acima da lista de falas.
2. Escolha somente o grupo atual ou todos os nove grupos.
3. Escolha **MP3 + HCA original**, **MP3**, **WAV** ou **HCA original**.
4. Escolha uma pasta e clique em **Exportar ZIPs**.

Cada grupo gera um ZIP independente. O formato **MP3 + HCA original** inclui uma cópia para ouvir e os bytes originais do jogo, como nos ZIPs anteriores. **WAV** é uma opção sem compressão com perdas para editar. Os tamanhos reais variam com o formato; não são fixados em 119 MB, 470 MB etc.

Os ZIPs contêm o índice `INDICE_DESTA_PARTE.jsonl`, com IDs, nomes e durações. Para recolocar seus áudios, extraia o ZIP, edite as falas desejadas e importe a pasta no grupo correspondente. Arquivos pertencentes a outro grupo aparecem na revisão e não são adicionados àquele grupo.

A exportação de muitas falas pode demorar. O botão **Cancelar** remove o ZIP incompleto e mantém os ZIPs que já terminaram. Arquivos existentes não são sobrescritos.

## Abrir no Linux

No pacote **Linux**, Python, Tkinter, CriCodecs e FFmpeg acompanham o programa.

1. Extraia o ZIP inteiro para uma pasta do computador.
2. Abra um terminal nessa pasta.
3. Execute:

```bash
bash Abrir_no_Linux.sh
```

O executável está em `programa_linux/EditorCPKAudio`. Mantenha a pasta `_internal` ao lado dele. Feito para Linux de 64 bits, com glibc 2.39 ou posterior, como Linux Mint 22 e Ubuntu 24.04. A interface precisa de uma sessão gráfica.

## Abrir pelo código-fonte

**Windows 10/11, pelo código-fonte:** instale Python **3.12 de 64 bits**, incluindo Python Launcher e Tcl/Tk. Extraia o pacote e abra `Abrir_no_Windows.bat`. A primeira abertura cria um ambiente virtual e baixa as dependências. Para usar o programa pronto sem instalar Python, baixe o executável na seção acima.

**Linux Mint/Ubuntu:** com Python 3.12, execute:

```bash
sudo apt install python3-tk python3-venv
bash Abrir_no_Linux.sh
```

No pacote de código-fonte, a primeira abertura também baixa as dependências em `.venv`. Depois, o programa funciona localmente. Os áudios não são enviados a um serviço externo.

## Fazer a primeira troca

1. Clique em **Abrir CPK** e selecione `dt510_bra_mobile_all.cpk`. Os ZIPs dos áudios antigos não são necessários.
2. Selecione um grupo, como `00_TEAM` ou `10_PLAYER_2`.
3. Busque a fala pelo nome interno ou ID. **Ouvir original** abre a fala no reprodutor do computador. **Exportar WAV** salva uma cópia para ouvir ou editar.
4. Selecione a fala e clique em **Associar áudio** para escolher seu WAV, MP3, FLAC, OGG, M4A, AAC, OPUS ou WMA.
5. Confira a lista de substituições à direita. Você pode remover trocas ou salvar a lista em JSON para continuar depois.
6. Escolha a duração e um nome de saída novo, por exemplo `narracao_modificada.cpk`.
7. Clique em **Gerar novo CPK** e aguarde a validação.

Faça primeiro uma troca pequena e teste o resultado no jogo. O programa não instala o CPK no celular e não produz as novas vozes: você fornece os áudios substitutos já gravados ou gerados.

## Escolher a duração

- **Manter a duração original:** corta o áudio novo quando ele é maior e acrescenta silêncio quando é menor. A duração em amostras permanece igual à original.
- **Usar a duração do novo áudio:** mantém a nova duração e atualiza os metadados de waveform e cue no ACB.

O padrão é manter a duração original. Um arquivo individual convertido para PCM tem limite de 64 MiB, cerca de 11 minutos em mono a 48 kHz.

## Importar uma pasta

Selecione o grupo correto e clique em **Importar pasta**. Coloque na pasta apenas as falas que você editou. São reconhecidos exemplos como:

```text
ID000000__BR_A1_T0_F0102.wav
00_TEAM__ID000001__BR_A1_T0_F0103.mp3
BR_A1_T0_F0104.flac
```

O ID pertence ao banco original do grupo selecionado. O programa confere nomes, bancos, grupos e duplicidades, e apresenta uma tela de revisão antes de adicionar associações válidas. Se houver duas versões para o mesmo ID, como WAV e MP3, deixe apenas uma. Arquivos sem correspondência não entram na lista.

A lista de falas mostra até 1.500 resultados por vez para manter a interface leve. **A busca percorre todos os áudios do grupo selecionado**. As quatro partes de `10_PLAYER` cobrem seus 41.176 áudios sem repetição.

## Arquivo de referência

O CPK original não está incluído no ZIP. Use sua cópia ou o [link fornecido no projeto](https://d1ln4m3c7n87ju.cloudfront.net/mobiledata/8ab31b5afaea56114427e1f01b81d001b079a0f59539f6db3f099816ca794055/r178350/dt510_bra_mobile_all.cpk).

- Tamanho: **827.291.697 bytes**.
- SHA-256: `053c5f60f74b10c4e86b8fb206d926fa712927bfd932e4e113e8bd04a560a636`.
- Bancos: `00_TEAM`, `10_PLAYER`, `20_MAIN`, `30_MAIN`, `40_MAIN`.
- Total: **54.833 áudios**.
- Chave HCA padrão: `14121473` / `0xD77A01`; subkey dos bancos: `0`.

O programa foi desenvolvido e testado com esse arquivo. Aceita layouts equivalentes com TOC antes do conteúdo, arquivos sem compressão, AWB AFS2 e cues diretas. Variantes com tabelas auxiliares, CRC adicional, cues complexas ou outro perfil de áudio são recusadas com uma mensagem.

## O que é conferido

O programa converte os substitutos para mono, 48 kHz, PCM16 e depois HCA v2, preservando o tamanho de bloco e a criptografia do original. Reconstrói offsets AWB e TOC, atualiza comprimentos, MD5 e cabeçalho AWB embutido no ACB. Os áudios não alterados são copiados sem recodificação.

Antes de finalizar, reabre o novo CPK, decodifica as substituições e compara os hashes de todas as entradas preservadas e de cada HCA não alterado nos bancos modificados. Confere novamente o SHA-256 do original. A validação é estrutural; o funcionamento dentro do jogo ainda depende de teste no próprio jogo.

Um arquivo `nome_da_saida.relatorio.json` acompanha a saída, com hashes, durações e lista de substituições. Destinos existentes são recusados. Falhas ou cancelamentos removem os arquivos temporários. Em sistemas de arquivos sem suporte a links, a cópia final validada pode levar alguns segundos adicionais.

Reserve pelo menos **3 GB livres** para uma troca pequena; arquivos maiores e muitas substituições podem exigir mais espaço. O processamento dos arquivos grandes usa blocos de 1 MiB. Os índices e um áudio individual em conversão ficam na memória.

## Modo de terminal

No Linux portátil, substitua `python iniciar.py` por `./programa_linux/EditorCPKAudio` se preferir.

```bash
python iniciar.py listar original.cpk
python iniciar.py grupos original.cpk
python iniciar.py listar original.cpk --grupo 10_PLAYER_2 --busca R000014
python iniciar.py exportar-zips original.cpk pasta_de_saida --grupo 40_MAIN --formato mp3_hca
python iniciar.py exportar-zips original.cpk pasta_de_saida --grupo todos --formato wav
python iniciar.py listar original.cpk --banco 00_TEAM --busca F0102
python iniciar.py exportar original.cpk 00_TEAM 0 fala_original.wav
python iniciar.py gerar original.cpk substituicoes.json novo.cpk
python iniciar.py gerar original.cpk substituicoes.json novo.cpk --nova-duracao
python iniciar.py repetir-audio original.cpk meu_audio.wav novo.cpk
python iniciar.py repetir-audio original.cpk meu_audio.mp3 novo.cpk --nova-duracao
python iniciar.py repetir-audio original.cpk meu_audio.wav novo.cpk --grupo 10_PLAYER_4
```

`exemplo_substituicoes.json` mostra o formato da lista. Caminhos relativos dos substitutos são resolvidos a partir da pasta do JSON. A interface também salva e carrega esse formato.

## Testes e compilação

```bash
python -m pip install -r requirements-dev.txt
CPK_TEST_FILE=/caminho/original.cpk python -m pytest -q
python tests/gui_smoke.py --cpk /caminho/original.cpk
```

O segundo teste abre uma janela e usa arquivos temporários. O CPK não é incluído nos testes; sem `CPK_TEST_FILE`, os testes que precisam dele são ignorados. Leia `VALIDACAO.md` para os resultados da entrega.

Para gerar um executável no próprio sistema de destino:

```bash
python -m PyInstaller --noconfirm --name EditorCPKAudio --onedir --collect-all cricodecs --collect-all imageio_ffmpeg iniciar.py
```

Para gerar o mesmo EXE e ZIP da distribuição Windows, execute no Windows com Python 3.12 de 64 bits:

```powershell
python -m pip install -r requirements-dev.txt
python scripts/build_windows.py
```

Os arquivos ficam em `release/`. O script verifica o executável fora do código-fonte, sem FFmpeg no PATH, antes de montar o pacote. O fluxo [Compilar e publicar Windows](https://github.com/L650111/Editor-de-narra-ao-efootball-moblie/actions/workflows/windows.yml) também faz isso no GitHub Actions: tags `v*` publicam os downloads em uma Release após os testes; a execução manual guarda o pacote como artefato da compilação.

Erros detalhados da interface, quando houver permissão, são registrados em `.editor_cpk_audio/erros.log` na pasta do usuário.

## Referências e componentes

- [CriCodecs](https://github.com/Youjose/CriCodecs) — codificação e decodificação HCA.
- [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) e [FFmpeg](https://ffmpeg.org/) — conversão dos formatos de entrada.
- [vgmstream: chaves HCA](https://github.com/vgmstream/vgmstream/blob/master/src/meta/hca_keys.h) — referência pública da chave.
- [Python](https://www.python.org/), Tcl/Tk e [PyInstaller](https://pyinstaller.org/) — interface e distribuição do executável.

O código deste projeto está em `LICENSE`. Os componentes de terceiros conservam suas próprias licenças; consulte `LICENCAS_TERCEIROS.md` e os avisos incluídos no pacote portátil.

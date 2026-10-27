# Validação da versão 1.2.0

Atualização preparada em 26/10/2026. Inclui escolha de um único áudio para repetir no CPK inteiro ou em um grupo, organização em nove grupos e exportação em ZIPs.

## Arquivo real utilizado

`dt510_bra_mobile_all.cpk`, 827.291.697 bytes, SHA-256:

`053c5f60f74b10c4e86b8fb206d926fa712927bfd932e4e113e8bd04a560a636`.

Foram identificados 54.833 áudios: 3.976 em `00_TEAM`, 41.176 em `10_PLAYER`, 6.134 em `20_MAIN`, 3.269 em `30_MAIN` e 278 em `40_MAIN`.

## Testes automáticos do mecanismo

**19 testes aprovados**, executados com o CPK real:

1. Leitura e validação da chave decimal/hexadecimal e rejeição de valores inválidos.
2. Leitura dos cinco bancos e conferência das quantidades.
3. Recusa de sobrescrita do original, de destino existente, de lista vazia e de IDs duplicados.
4. Associação por nome/ID, detecção de duplicidades, nome divergente, ID inexistente e pasta de outro banco.
5. Cancelamento antes do processamento e durante a montagem, com remoção dos temporários.
6. Recusa de entrada que não contém áudio, sem deixar CPK parcial.
7. Substituição simultânea de uma fala em cada um dos cinco bancos, usando nova duração. O sinal de teste de 440 Hz, estéreo e 44,1 kHz foi convertido para HCA mono a 48 kHz. O resultado recuperado teve 65.760 amostras e seu conteúdo acústico foi conferido.
8. Preservação da duração original com corte de trecho longo e preenchimento de trecho curto com silêncio. A contagem de amostras e o silêncio final foram conferidos.
9. Particionamento exato dos 54.833 IDs nos nove grupos, sem omissões ou duplicidades. Os limites foram conferidos nos índices dos ZIPs antigos.
10. Exportação HCA em ZIP com bytes idênticos ao original e CRC válido.
11. Exportação WAV em ZIP com contagem correta de amostras e nomes reconhecidos na reimportação.
12. Exportação MP3 em ZIP e reconhecimento de nomes e IDs para reimportar.
13. Exportação combinada MP3 + HCA original e preservação dos bytes HCA.
14. Cancelamento da exportação mantendo o ZIP já concluído e removendo o ZIP incompleto.
15. Reconhecimento de pastas como `10_PLAYER_1` e identificação de seu banco original durante a importação.
16. Associação de um arquivo escolhido a todos os 54.833 IDs, ou apenas aos 3.966 IDs do grupo `10_PLAYER_4`, com recusa de grupo inexistente e cancelamento.
17. Geração e reabertura de um CPK com **todas as 54.833 falas substituídas por um mesmo áudio**. A entrada foi convertida uma vez, uma codificação HCA foi reutilizada e todas as posições foram verificadas. O sinal de teste de 440 Hz foi recuperado dos cinco bancos e a duração de todas as waveforms foi conferida.
18. Reutilização da entrada preservando durações originais diferentes, incluindo corte e preenchimento com silêncio. As contagens de amostras e o silêncio final foram conferidos.
19. Recusa de finalização se o arquivo de áudio escolhido for alterado durante o processamento; remoção dos temporários e preservação do CPK original.

A reconstrução foi reaberta, os áudios substituídos foram decodificados e os hashes das entradas preservadas e dos demais HCAs foram comparados. IDs, nomes, durações de cues, MD5 AWB e cabeçalhos embutidos foram conferidos. Um leitor AFS2 independente, do CriCodecs, confirmou a contagem, o alinhamento, os IDs, os offsets e os tamanhos de todas as entradas de um banco reconstruído.

## Interface gráfica

Teste com janela real em Linux, usando Tk 8.6 e um display virtual:

- Abrir o CPK, buscar uma fala e associar um novo WAV.
- Abrir **Repetir áudio**, escolher um WAV pelo seletor e adicionar as 54.833 associações à lista. Conferir que todas apontam para o arquivo escolhido e limpar a lista pelo novo botão.
- Exportar um original em WAV.
- Salvar, remover e recarregar a lista JSON.
- Trocar para `10_PLAYER_4` e encontrar o ID 41175, conferindo também que o ID 0 não pertence àquela parte.
- Conferir os nove grupos no seletor e exportar `40_MAIN.zip` pela interface, com 278 HCAs originais e CRC válido.
- Importar uma pasta, revisar e aceitar a associação.
- Gerar um CPK pela interface com duas substituições e verificar o relatório.

Resultado: **aprovado**. A apresentação da interface também foi inspecionada visualmente.

## Executável Linux

Empacotado com PyInstaller 6.22.3, Python 3.12.14, Tcl/Tk 8.6.14, CriCodecs 1.2.0 e imageio-ffmpeg 0.6.0. Arquitetura x86-64, glibc 2.39.

O executável abriu a interface sem Python ou Tcl/Tk externos. Também gerou e validou um CPK com o `PATH` sem acesso ao FFmpeg do sistema, usando o conversor incluído no pacote. Essa saída apresentou o mesmo SHA-256 da saída equivalente gerada pelo código-fonte:

`aa342367d86cec3c3e9c535b47e4a215ce0ef9bef40eff2b24c305a6efa46d0f`.

Na versão 1.1, o executável foi recompilado e abriu a nova interface sem dependências externas de Python/Tcl/Tk. Listou os nove grupos com as contagens e intervalos corretos. Também exportou o grupo `40_MAIN` inteiro usando exclusivamente o FFmpeg incluído: **278 pares MP3/HCA** em um ZIP de **87.681.913 bytes**, com índice, CRCs conferidos e nomes preservados.

Na versão 1.2, o executável também abriu sem dependências externas de Python/Tcl/Tk e gerou um CPK com os **54.833 áudios substituídos por uma única gravação de teste**, usando o FFmpeg incluído. A montagem foi reaberta e validada pelo próprio mecanismo antes da finalização. O botão da interface permite escolher outra gravação no computador do usuário.

## Limites da verificação

- O CPK modificado **não foi testado dentro do jogo**. Validação estrutural não comprova a aceitação pelo jogo.
- O iniciador Windows e o código para Windows foram fornecidos; não foi executado teste em um computador Windows e não foi gerado `.exe` para esse sistema.
- Os testes cobrem o arquivo de referência e seu perfil. Variantes não suportadas são recusadas.

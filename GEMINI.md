# REGRA MASTER DO PROJETO: LIMPEZA AUTOMÁTICA DE GRAVAÇÕES DE NAVEGADOR

## Contexto
O Antigravity IDE executa automações de navegador (`browser_subagent`) para validações visuais. Essas execuções geram milhares de frames em `.jpg` na pasta `browser_recordings`, consumindo grande volume de armazenamento se acumulados.

## Diretriz Obrigatória (Master Rule)
Sempre que o assistente terminar qualquer ciclo de testes, validações ou interações com o navegador:
1. **Limpeza Mandatória:** Executar imediatamente o comando de exclusão das gravações geradas para liberar o espaço em disco.
2. **Caminho:** `C:\Users\robym\.gemini\antigravity-ide\browser_recordings\`
3. **Comando de Limpeza:**
   ```cmd
   cmd /c "if exist C:\Users\robym\.gemini\antigravity-ide\browser_recordings (rd /s /q C:\Users\robym\.gemini\antigravity-ide\browser_recordings)"
   ```
4. **Sem Acúmulo:** Nunca encerrar uma entrega ou sessão de testes visuais deixando a pasta de gravações ocupando espaço no disco.

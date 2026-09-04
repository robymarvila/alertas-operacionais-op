# REGRA: LIMPEZA DE GRAVAÇÕES DE NAVEGADOR

## Diretriz Obrigatória
Após finalizar qualquer inspeção ou teste com o navegador (`browser_subagent`), o agente deve sempre excluir os arquivos temporários de gravação para não consumir espaço em disco:

```cmd
cmd /c "if exist C:\Users\robym\.gemini\antigravity-ide\browser_recordings (rd /s /q C:\Users\robym\.gemini\antigravity-ide\browser_recordings)"
```

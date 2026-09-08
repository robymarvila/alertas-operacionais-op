# REGRAS MASTER DO PROJETO

---

## REGRA 1: SUBIDA PARA O GITHUB APENAS SOB SOLICITAÇÃO EXPLÍCITA DO USUÁRIO (REGRA MÁXIMA)

### Diretriz Obrigatória (Git & Versionamento Remoto)
1. **Proibição Absoluta de Push Automático:** O assistente está estritamente proibido de executar `git push` para o GitHub ou qualquer repositório remoto por conta própria.
2. **Validação Local Primeiro:** Qualquer alteração no código deve ser implementada e testada estritamente no ambiente local.
3. **Autorização Obrigatória:** O assistente SÓ PODE fazer o commit e push para o GitHub após os testes estarem concluídos E quando o USUÁRIO solicitar explicitamente (ex: *"pode subir para o GitHub"*, *"sobe a nova versão"*).
4. **Sem Exceções:** Mesmo que uma funcionalidade esteja 100% pronta e testada, o assistente deve aguardar a ordem expressa do usuário para subir para o GitHub.

---

## REGRA 2: LIMPEZA AUTOMÁTICA DE GRAVAÇÕES DE NAVEGADOR

### Contexto
O Antigravity IDE executa automações de navegador (`browser_subagent`) para validações visuais. Essas execuções geram milhares de frames em `.jpg` na pasta `browser_recordings`, consumindo grande volume de armazenamento se acumulados.

### Diretriz Obrigatória (Master Rule)
Sempre que o assistente terminar qualquer ciclo de testes, validações ou interações com o navegador:
1. **Limpeza Mandatória:** Executar imediatamente o comando de exclusão das gravações geradas para liberar o espaço em disco.
2. **Caminho:** `C:\Users\robym\.gemini\antigravity-ide\browser_recordings\`
3. **Comando de Limpeza:**
   ```cmd
   cmd /c "if exist C:\Users\robym\.gemini\antigravity-ide\browser_recordings (rd /s /q C:\Users\robym\.gemini\antigravity-ide\browser_recordings)"
   ```
4. **Sem Acúmulo:** Nunca encerrar uma entrega ou sessão de testes visuais deixando a pasta de gravações ocupando espaço no disco.

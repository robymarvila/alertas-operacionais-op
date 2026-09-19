@echo off
chcp 65001 >nul
title Configurar Esta Máquina como Servidor Principal (Máquina 1)
echo ==============================================================================
echo  CONFIGURANDO ESTA MÁQUINA COMO SERVIDOR CCO PRINCIPAL (MÁQUINA 1 - MASTER)
echo ==============================================================================
echo.
python -c "from cluster_manager import cluster_manager; cluster_manager.save_config({'node_id': 'MAQUINA_1_PRINCIPAL', 'node_label': 'Servidor CCO Principal (Máquina 1)', 'role': 'PRIMARY', 'is_feeding_db': True, 'auto_failover_enabled': True}); print('[OK] Esta máquina agora está configurada como MÁQUINA 1 - PRINCIPAL (ATIVO)!')"
echo.
echo Pressione qualquer tecla para fechar...
pause >nul

@echo off
chcp 65001 >nul
title Configurar Esta Máquina como Servidor de Backup (Redundante)
echo ==============================================================================
echo  CONFIGURANDO ESTA MÁQUINA COMO SERVIDOR CCO REDUNDANTE (MÁQUINA 2 - BACKUP)
echo ==============================================================================
echo.
python -c "from cluster_manager import cluster_manager; cluster_manager.save_config({'node_id': 'MAQUINA_2_BACKUP', 'node_label': 'Servidor CCO Redundante (Máquina 2)', 'role': 'STANDBY', 'is_feeding_db': False, 'auto_failover_enabled': True}); print('[OK] Esta máquina agora está configurada como MÁQUINA 2 - BACKUP (STANDBY)!')"
echo.
echo Pressione qualquer tecla para fechar...
pause >nul

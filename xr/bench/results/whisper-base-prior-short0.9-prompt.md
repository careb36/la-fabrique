## whisper-base-prior-short0.9-prompt

| language | phrases | commands right | WER | language right | s/phrase |
|---|---|---|---|---|---|
| en | 186 | 93% | 10.0% | 100% | 1.25 |
| es | 248 | 70% | 31.8% | 100% | 1.21 |
| all | 434 | 80% | 22.5% | 100% | 1.23 |

| voice | commands right | WER |
|---|---|---|
| en-heart | 98% | 4.8% |
| en-us-lessac | 95% | 8.8% |
| en-us-ryan | 85% | 16.4% |
| es-ar-daniela | 58% | 45.1% |
| es-dora | 79% | 27.6% |
| es-es-davefx | 63% | 32.2% |
| es-mx-claude | 81% | 22.3% |

| intent | es | en |
|---|---|---|
| approve | 39% | 95% |
| help | 83% | 89% |
| launch:ci | 58% | 78% |
| launch:csv | 75% | 78% |
| launch:reset | 83% | 100% |
| mute | 67% | 89% |
| next | 75% | 83% |
| no | 100% | 89% |
| none | 100% | 100% |
| pause | 69% | 83% |
| recenter | 67% | 100% |
| reject | 46% | 100% |
| restart | 67% | 100% |
| resume | 63% | 100% |
| status | 94% | 100% |
| unmute | 88% | 83% |
| yes | 81% | 92% |

Misses: 87

- en-heart/en-no-1: said “No.”, heard “Now.” (en), understood none (wanted no)
- en-us-lessac/en-launch-ci-1: said “Launch the CI one.”, heard “Launch the C-di-1.” (en), understood launch:? (wanted launch:ci)
- en-us-lessac/en-launch-csv-3: said “Go ahead with the CSV.”, heard “Go ahead with the C-desv.” (en), understood launch:? (wanted launch:csv)
- en-us-lessac/en-unmute-1: said “Unmute.”, heard “Amute.” (en), understood none (wanted unmute)
- en-us-ryan/en-approve-4: said “Ship it.”, heard “Shut that.” (en), understood none (wanted approve)
- en-us-ryan/en-help-2: said “Help.”, heard “Oh.” (en), understood none (wanted help)
- en-us-ryan/en-launch-ci-1: said “Launch the CI one.”, heard “Lunge the CI one.” (en), understood none (wanted launch:ci)
- en-us-ryan/en-launch-csv-3: said “Go ahead with the CSV.”, heard “Go ahead with the cswe.” (en), understood launch:? (wanted launch:csv)
- en-us-ryan/en-mute-1: said “Mute.”, heard “Close.” (en), understood none (wanted mute)
- en-us-ryan/en-next-1: said “Next sprint.”, heard “Next. Sprints.” (en), understood none (wanted next)
- en-us-ryan/en-pause-1: said “Pause.”, heard “Voice.” (en), understood none (wanted pause)
- en-us-ryan/en-pause-3: said “Wait.”, heard “What.” (en), understood none (wanted pause)
- en-us-ryan/en-yes-3: said “Confirmed.”, heard “Tim Verne.” (en), understood none (wanted yes)
- es-ar-daniela/es-approve-1: said “Aprobá.”, heard “Tapelo.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-3: said “Dale, aprobá la entrega.”, heard “Dale. Está por la entrada.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-4: said “Está bien, apruebo.”, heard “Está bien. Apluevo.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-5: said “Apruebe la entrega, por favor.”, heard “Aprove la entidad. Por favor.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-7: said “Eh, sí, aprobado.”, heard “Esí. Adelante.” (es), understood yes (wanted approve)
- es-ar-daniela/es-help-1: said “¿Qué puedo decir?”, heard “Te puedo decir.” (es), understood none (wanted help)
- es-ar-daniela/es-help-2: said “Ayuda.”, heard “Adelante.” (es), understood yes (wanted help)
- es-ar-daniela/es-launch-ci-2: said “Arrancá la tercera tarea.”, heard “Arrancá.” (es), understood launch:? (wanted launch:ci)
- es-ar-daniela/es-launch-csv-2: said “Lanzá la segunda.”, heard “Lensá la segunda.” (es), understood none (wanted launch:csv)
- es-ar-daniela/es-launch-csv-3: said “Dale con el CSV.”, heard “Dale con ese.” (es), understood launch:? (wanted launch:csv)
- es-ar-daniela/es-launch-reset-3: said “Empezá con la de la contraseña.”, heard “Empezá con la de la contrasella.” (es), understood launch:? (wanted launch:reset)
- es-ar-daniela/es-mute-1: said “Silencio.”, heard “Cienso.” (es), understood none (wanted mute)
- es-ar-daniela/es-mute-3: said “Callate un rato.”, heard “Que ya te he congato.” (es), understood none (wanted mute)
- es-ar-daniela/es-next-1: said “Siguiente sprint.”, heard “Si entro.” (es), understood none (wanted next)
- es-ar-daniela/es-recenter-2: said “Vení acá.”, heard “Venía acá.” (es), understood none (wanted recenter)
- es-ar-daniela/es-recenter-3: said “Traé todo al frente.”, heard “Todo el frente.” (es), understood none (wanted recenter)
- es-ar-daniela/es-reject-1: said “Devolvela.”, heard “Te olve la.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-3: said “No, rechazala.”, heard “No os puchas a la.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-5: said “Devuélvela al desarrollador.”, heard “Te huele el desarrollador.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-7: said “Rechazada.”, heard “De hecho, sal.” (es), understood none (wanted reject)
- es-ar-daniela/es-restart-1: said “Reiniciá.”, heard “Inicia.” (es), understood launch:? (wanted restart)
- es-ar-daniela/es-resume-1: said “Seguí.”, heard “Sí.” (es), understood yes (wanted resume)
- es-ar-daniela/es-resume-3: said “Reanudá el sprint.”, heard “Tenlois.” (es), understood none (wanted resume)
- es-ar-daniela/es-resume-4: said “Dale, seguimos.”, heard “Dale.” (es), understood yes (wanted resume)
- es-ar-daniela/es-status-1: said “¿Cómo va?”, heard “Cono.” (es), understood none (wanted status)
- es-ar-daniela/es-yes-3: said “Confirmo.”, heard “Confierelo.” (es), understood none (wanted yes)
- es-dora/es-approve-3: said “Dale, aprobá la entrega.”, heard “Dale a probarla entrega.” (es), understood none (wanted approve)
- es-dora/es-approve-4: said “Está bien, apruebo.”, heard “Está bien a prueba.” (es), understood none (wanted approve)
- es-dora/es-approve-5: said “Apruebe la entrega, por favor.”, heard “Aprove la entrega. Por favor.” (es), understood none (wanted approve)
- es-dora/es-launch-ci-2: said “Arrancá la tercera tarea.”, heard “Ranked.” (en), understood none (wanted launch:ci)
- es-dora/es-pause-1: said “Pausá.”, heard “Bosa.” (es), understood none (wanted pause)
- es-dora/es-pause-3: said “Esperá.”, heard “Espeda.” (es), understood none (wanted pause)
- es-dora/es-recenter-2: said “Vení acá.”, heard “Beníacal.” (es), understood none (wanted recenter)
- es-dora/es-reject-1: said “Devolvela.”, heard “De volvila.” (es), understood none (wanted reject)
- es-dora/es-reject-3: said “No, rechazala.”, heard “No recasala.” (es), understood none (wanted reject)
- es-dora/es-reject-5: said “Devuélvela al desarrollador.”, heard “Te vuelve la al desarrollador.” (es), understood none (wanted reject)
- es-dora/es-restart-1: said “Reiniciá.”, heard “Renicia.” (es), understood none (wanted restart)
- es-dora/es-resume-1: said “Seguí.”, heard “Saga ahí.” (es), understood none (wanted resume)
- es-dora/es-yes-1: said “Sí.”, heard “Se llama.” (es), understood none (wanted yes)
- es-es-davefx/es-approve-1: said “Aprobá.”, heard “Que pasa.” (es), understood status (wanted approve)
- es-es-davefx/es-approve-2: said “Aprobala.”, heard “Ravala.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-3: said “Dale, aprobá la entrega.”, heard “Dale. Aproveada la entrega.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-4: said “Está bien, apruebo.”, heard “Está bien. Adelante.” (es), understood yes (wanted approve)
- es-es-davefx/es-approve-5: said “Apruebe la entrega, por favor.”, heard “No provee la entrega. Por favor.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-7: said “Eh, sí, aprobado.”, heard “Sí. Está probado.” (es), understood none (wanted approve)
- es-es-davefx/es-launch-ci-1: said “Lanzá la del CI.”, heard “Lanzá la del fe.” (es), understood launch:? (wanted launch:ci)
- es-es-davefx/es-launch-ci-2: said “Arrancá la tercera tarea.”, heard “Alancala. Te ferataría.” (es), understood none (wanted launch:ci)
- es-es-davefx/es-launch-ci-3: said “Empezá la del runner.”, heard “Empezá la del bonear.” (es), understood launch:? (wanted launch:ci)
- es-es-davefx/es-launch-reset-2: said “Arrancá la primera.”, heard “Para encar la primera.” (es), understood none (wanted launch:reset)
- es-es-davefx/es-mute-1: said “Silencio.”, heard “Si le enfee.” (es), understood none (wanted mute)
- es-es-davefx/es-mute-3: said “Callate un rato.”, heard “Casiate un plato.” (es), understood none (wanted mute)
- es-es-davefx/es-pause-1: said “Pausá.”, heard “Gracias.” (es), understood none (wanted pause)
- es-es-davefx/es-pause-4: said “Poné pausa, por favor.”, heard “Poné por favor.” (es), understood none (wanted pause)
- es-es-davefx/es-recenter-2: said “Vení acá.”, heard “Vení.” (es), understood none (wanted recenter)
- es-es-davefx/es-reject-1: said “Devolvela.”, heard “Debo el bella.” (es), understood none (wanted reject)
- es-es-davefx/es-reject-3: said “No, rechazala.”, heard “No. Puede hacerla.” (es), understood none (wanted reject)
- es-es-davefx/es-reject-5: said “Devuélvela al desarrollador.”, heard “De vuelve al desarrollador.” (es), understood none (wanted reject)
- es-es-davefx/es-reject-7: said “Rechazada.”, heard “Deja nada.” (es), understood none (wanted reject)
- es-es-davefx/es-restart-1: said “Reiniciá.”, heard “Vein.” (es), understood none (wanted restart)
- es-es-davefx/es-restart-2: said “Empezá de nuevo.”, heard “Empezá del nuevo.” (es), understood launch:? (wanted restart)
- es-es-davefx/es-resume-1: said “Seguí.”, heard “Tiene.” (es), understood none (wanted resume)
- es-es-davefx/es-yes-1: said “Sí.”, heard “T.” (es), understood none (wanted yes)
- es-mx-claude/es-approve-4: said “Está bien, apruebo.”, heard “Está bien. A prueba.” (es), understood none (wanted approve)
- es-mx-claude/es-approve-5: said “Apruebe la entrega, por favor.”, heard “Apreve la entrega. Por favor.” (es), understood none (wanted approve)
- es-mx-claude/es-approve-6: said “Me parece bien, aceptala.”, heard “Me parece bien. Aseptal.” (es), understood none (wanted approve)
- es-mx-claude/es-launch-csv-3: said “Dale con el CSV.”, heard “Dale con el ccv.” (es), understood launch:? (wanted launch:csv)
- es-mx-claude/es-next-1: said “Siguiente sprint.”, heard “Siguiente esplíntaro.” (es), understood none (wanted next)
- es-mx-claude/es-pause-1: said “Pausá.”, heard “Vos.” (es), understood none (wanted pause)
- es-mx-claude/es-reject-1: said “Devolvela.”, heard “De volverla.” (es), understood none (wanted reject)
- es-mx-claude/es-reject-3: said “No, rechazala.”, heard “No plecho sala.” (es), understood none (wanted reject)
- es-mx-claude/es-reject-5: said “Devuélvela al desarrollador.”, heard “Debo el vellal desarrollador.” (es), understood none (wanted reject)
- es-mx-claude/es-reject-7: said “Rechazada.”, heard “Deja Sada.” (es), understood none (wanted reject)
- es-mx-claude/es-resume-1: said “Seguí.”, heard “Sidi.” (es), understood none (wanted resume)
- es-mx-claude/es-unmute-2: said “Con sonido.”, heard “Consonido.” (es), understood none (wanted unmute)

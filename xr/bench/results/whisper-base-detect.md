## whisper-base-detect

| language | phrases | commands right | WER | language right | s/phrase |
|---|---|---|---|---|---|
| en | 186 | 87% | 14.0% | 100% | 2.40 |
| es | 248 | 52% | 50.8% | 83% | 2.56 |
| all | 434 | 67% | 35.0% | 90% | 2.49 |

| voice | commands right | WER |
|---|---|---|
| en-heart | 97% | 5.8% |
| en-us-lessac | 87% | 11.3% |
| en-us-ryan | 76% | 25.0% |
| es-ar-daniela | 31% | 67.0% |
| es-dora | 63% | 44.2% |
| es-es-davefx | 47% | 55.2% |
| es-mx-claude | 68% | 36.6% |

| intent | es | en |
|---|---|---|
| approve | 39% | 86% |
| help | 50% | 89% |
| launch:ci | 8% | 56% |
| launch:csv | 33% | 67% |
| launch:reset | 67% | 89% |
| mute | 50% | 78% |
| next | 63% | 83% |
| no | 83% | 78% |
| none | 100% | 100% |
| pause | 63% | 67% |
| recenter | 50% | 100% |
| reject | 43% | 95% |
| restart | 42% | 100% |
| resume | 44% | 100% |
| status | 75% | 100% |
| unmute | 25% | 83% |
| yes | 50% | 83% |

Misses: 144

- en-heart/en-launch-ci-1: said “Launch the CI one.”, heard “Launch the CI1.” (en), understood launch:? (wanted launch:ci)
- en-heart/en-no-1: said “No.”, heard “Now.” (en), understood none (wanted no)
- en-us-lessac/en-launch-ci-1: said “Launch the CI one.”, heard “Launch the C-dye 1.” (en), understood launch:? (wanted launch:ci)
- en-us-lessac/en-launch-ci-3: said “Start the runner one.”, heard “Tart the Runner 1.” (en), understood none (wanted launch:ci)
- en-us-lessac/en-launch-csv-3: said “Go ahead with the CSV.”, heard “Go ahead with the C-DESV.” (en), understood launch:? (wanted launch:csv)
- en-us-lessac/en-launch-reset-2: said “Start the first one.”, heard “Sort the first one.” (en), understood none (wanted launch:reset)
- en-us-lessac/en-mute-2: said “Turn the sound off.”, heard “Turn the cell on off.” (en), understood none (wanted mute)
- en-us-lessac/en-pause-4: said “Pause it, please.”, heard “positive, please.” (en), understood none (wanted pause)
- en-us-lessac/en-reject-7: said “Rejected.”, heard “Redacted.” (en), understood none (wanted reject)
- en-us-lessac/en-unmute-1: said “Unmute.”, heard “Amute” (en), understood none (wanted unmute)
- en-us-ryan/en-approve-1: said “Approve.”, heard “I'd prove.” (en), understood none (wanted approve)
- en-us-ryan/en-approve-2: said “Approve it.”, heard “Approach it.” (en), understood none (wanted approve)
- en-us-ryan/en-approve-4: said “Ship it.”, heard “Shut that.” (en), understood none (wanted approve)
- en-us-ryan/en-help-2: said “Help.”, heard “Oh” (en), understood none (wanted help)
- en-us-ryan/en-launch-ci-1: said “Launch the CI one.”, heard “Lunge the CI1” (en), understood none (wanted launch:ci)
- en-us-ryan/en-launch-csv-1: said “Launch the CSV export.”, heard “Lunge the Z-SB export.” (en), understood none (wanted launch:csv)
- en-us-ryan/en-launch-csv-3: said “Go ahead with the CSV.”, heard “Go ahead with the CSWe.” (en), understood launch:? (wanted launch:csv)
- en-us-ryan/en-mute-1: said “Mute.”, heard “Close.” (en), understood none (wanted mute)
- en-us-ryan/en-next-1: said “Next sprint.”, heard “next sprains” (en), understood none (wanted next)
- en-us-ryan/en-no-1: said “No.”, heard “Well?” (en), understood none (wanted no)
- en-us-ryan/en-pause-1: said “Pause.”, heard “Boys” (en), understood none (wanted pause)
- en-us-ryan/en-pause-3: said “Wait.”, heard “What?” (en), understood none (wanted pause)
- en-us-ryan/en-pause-4: said “Pause it, please.”, heard “Positive please.” (en), understood none (wanted pause)
- en-us-ryan/en-yes-1: said “Yes.”, heard “That's...” (en), understood none (wanted yes)
- en-us-ryan/en-yes-3: said “Confirmed.”, heard “10-3” (en), understood none (wanted yes)
- es-ar-daniela/es-approve-1: said “Aprobá.”, heard “April” (en), understood none (wanted approve)
- es-ar-daniela/es-approve-2: said “Aprobala.”, heard “Aprovala.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-3: said “Dale, aprobá la entrega.”, heard “de Alesta Póla Entreva.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-4: said “Está bien, apruebo.”, heard “Está bien la prueba.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-5: said “Apruebe la entrega, por favor.”, heard “Apluye la entidad, por favor.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-7: said “Eh, sí, aprobado.”, heard “así, bye bye” (es), understood none (wanted approve)
- es-ar-daniela/es-help-1: said “¿Qué puedo decir?”, heard “te puede vacir.” (es), understood none (wanted help)
- es-ar-daniela/es-help-2: said “Ayuda.”, heard “¡Adiós!” (es), understood none (wanted help)
- es-ar-daniela/es-help-3: said “¿Qué órdenes entendés?”, heard “¿Qué hora les entendés?” (es), understood none (wanted help)
- es-ar-daniela/es-launch-ci-1: said “Lanzá la del CI.”, heard “Lanzala de Sai” (es), understood launch:? (wanted launch:ci)
- es-ar-daniela/es-launch-ci-2: said “Arrancá la tercera tarea.”, heard “Arranquletes será estará” (es), understood none (wanted launch:ci)
- es-ar-daniela/es-launch-ci-3: said “Empezá la del runner.”, heard “Empezala del Runaer” (es), understood launch:? (wanted launch:ci)
- es-ar-daniela/es-launch-csv-1: said “Lanzá la exportación CSV.”, heard “Lensar a la exportación USB” (es), understood none (wanted launch:csv)
- es-ar-daniela/es-launch-csv-2: said “Lanzá la segunda.”, heard “Lensar la segunda.” (es), understood none (wanted launch:csv)
- es-ar-daniela/es-launch-csv-3: said “Dale con el CSV.”, heard “Tal con ese CV.” (es), understood none (wanted launch:csv)
- es-ar-daniela/es-launch-reset-1: said “Lanzá el password reset.”, heard “y en sal pasó el reset.” (es), understood none (wanted launch:reset)
- es-ar-daniela/es-launch-reset-2: said “Arrancá la primera.”, heard “Ahora con la primera.” (es), understood none (wanted launch:reset)
- es-ar-daniela/es-launch-reset-3: said “Empezá con la de la contraseña.”, heard “Empezamos con la de la Contracella.” (es), understood launch:? (wanted launch:reset)
- es-ar-daniela/es-mute-1: said “Silencio.”, heard “Gracias y hasta la próxima.” (es), understood none (wanted mute)
- es-ar-daniela/es-mute-2: said “Sacá el sonido.”, heard “Sacal sonía” (es), understood none (wanted mute)
- es-ar-daniela/es-mute-3: said “Callate un rato.”, heard “que ya te he congelado.” (es), understood none (wanted mute)
- es-ar-daniela/es-next-1: said “Siguiente sprint.”, heard “See you in the next video.” (en), understood none (wanted next)
- es-ar-daniela/es-no-1: said “No.”, heard “Nah.” (en), understood none (wanted no)
- es-ar-daniela/es-pause-1: said “Pausá.”, heard “Posa.” (en), understood none (wanted pause)
- es-ar-daniela/es-recenter-1: said “Centrá los paneles.”, heard “entre los paneles.” (es), understood none (wanted recenter)
- es-ar-daniela/es-recenter-2: said “Vení acá.”, heard “de ni acá” (es), understood none (wanted recenter)
- es-ar-daniela/es-recenter-3: said “Traé todo al frente.”, heard “de todo el frente.” (es), understood none (wanted recenter)
- es-ar-daniela/es-reject-1: said “Devolvela.”, heard “te volvés la” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-3: said “No, rechazala.”, heard “Nos vemos en la próxima.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-5: said “Devuélvela al desarrollador.”, heard “de huele al desarrollador.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-7: said “Rechazada.”, heard “hecho salva.” (es), understood none (wanted reject)
- es-ar-daniela/es-restart-1: said “Reiniciá.”, heard “enicia” (es), understood none (wanted restart)
- es-ar-daniela/es-restart-2: said “Empezá de nuevo.”, heard “Empezada nuevo.” (es), understood launch:? (wanted restart)
- es-ar-daniela/es-restart-3: said “Arrancá otra vez desde cero.”, heard “Arancados a través de cero.” (es), understood none (wanted restart)
- es-ar-daniela/es-resume-1: said “Seguí.”, heard “Say” (en), understood none (wanted resume)
- es-ar-daniela/es-resume-3: said “Reanudá el sprint.”, heard “then L. Springt.” (en), understood none (wanted resume)
- es-ar-daniela/es-resume-4: said “Dale, seguimos.”, heard “tal es aimos” (es), understood none (wanted resume)
- es-ar-daniela/es-status-1: said “¿Cómo va?”, heard “Konua” (en), understood none (wanted status)
- es-ar-daniela/es-unmute-1: said “Poné el sonido.”, heard “por eso ni yo” (es), understood none (wanted unmute)
- es-ar-daniela/es-unmute-2: said “Con sonido.”, heard “Consenio” (es), understood none (wanted unmute)
- es-ar-daniela/es-yes-1: said “Sí.”, heard “See ya.” (en), understood none (wanted yes)
- es-ar-daniela/es-yes-3: said “Confirmo.”, heard “Confeira” (es), understood none (wanted yes)
- es-ar-daniela/es-yes-4: said “Exacto, hacelo.”, heard “excepto raselo.” (es), understood none (wanted yes)
- es-dora/es-approve-2: said “Aprobala.”, heard “aprovala” (en), understood none (wanted approve)
- es-dora/es-approve-3: said “Dale, aprobá la entrega.”, heard “Dale a Probala Intrega.” (es), understood none (wanted approve)
- es-dora/es-approve-4: said “Está bien, apruebo.”, heard “Está bien a prueba.” (es), understood none (wanted approve)
- es-dora/es-approve-5: said “Apruebe la entrega, por favor.”, heard “Aprovebe la entrega por favor.” (es), understood none (wanted approve)
- es-dora/es-help-2: said “Ayuda.”, heard “Are you there?” (en), understood none (wanted help)
- es-dora/es-launch-ci-1: said “Lanzá la del CI.”, heard “Lanzala del C.” (es), understood launch:? (wanted launch:ci)
- es-dora/es-launch-ci-2: said “Arrancá la tercera tarea.”, heard “Rangkala, Tehrsera, Tarea.” (en), understood none (wanted launch:ci)
- es-dora/es-launch-ci-3: said “Empezá la del runner.”, heard “Empezala del RUNER.” (es), understood launch:? (wanted launch:ci)
- es-dora/es-launch-csv-3: said “Dale con el CSV.”, heard “Dale con el CSUBE.” (es), understood launch:? (wanted launch:csv)
- es-dora/es-pause-1: said “Pausá.”, heard “Both sides.” (en), understood none (wanted pause)
- es-dora/es-pause-3: said “Esperá.”, heard “It's been all.” (en), understood none (wanted pause)
- es-dora/es-recenter-2: said “Vení acá.”, heard “Benia Carl” (en), understood none (wanted recenter)
- es-dora/es-reject-1: said “Devolvela.”, heard “de Volvila.” (es), understood none (wanted reject)
- es-dora/es-reject-3: said “No, rechazala.”, heard “No Recha Salas.” (es), understood none (wanted reject)
- es-dora/es-reject-5: said “Devuélvela al desarrollador.”, heard “te vuelve la al desarrollador.” (es), understood none (wanted reject)
- es-dora/es-reject-7: said “Rechazada.”, heard “Recha Sada” (es), understood none (wanted reject)
- es-dora/es-restart-2: said “Empezá de nuevo.”, heard “start the new.” (en), understood launch:? (wanted restart)
- es-dora/es-resume-1: said “Seguí.”, heard “Sagar.” (en), understood none (wanted resume)
- es-dora/es-resume-3: said “Reanudá el sprint.”, heard “Reano da el sprint” (es), understood none (wanted resume)
- es-dora/es-status-1: said “¿Cómo va?”, heard “Come on by.” (en), understood none (wanted status)
- es-dora/es-unmute-2: said “Con sonido.”, heard “Consonido” (es), understood none (wanted unmute)
- es-dora/es-yes-1: said “Sí.”, heard “Thank you.” (en), understood none (wanted yes)
- es-dora/es-yes-2: said “Sí, dale.”, heard “See you next time.” (en), understood none (wanted yes)
- es-es-davefx/es-approve-1: said “Aprobá.”, heard “you” (en), understood none (wanted approve)
- es-es-davefx/es-approve-2: said “Aprobala.”, heard “Y ahora lo vale.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-4: said “Está bien, apruebo.”, heard “Está bien, ¡ah, por nuevo!” (es), understood none (wanted approve)
- es-es-davefx/es-approve-5: said “Apruebe la entrega, por favor.”, heard “nos proveemos de la entrega por favor” (es), understood none (wanted approve)
- es-es-davefx/es-approve-7: said “Eh, sí, aprobado.”, heard “Sí, está probado.” (es), understood none (wanted approve)
- es-es-davefx/es-help-2: said “Ayuda.”, heard “Thank you.” (en), understood none (wanted help)
- es-es-davefx/es-launch-ci-1: said “Lanzá la del CI.”, heard “Lanzala del fe.” (es), understood launch:? (wanted launch:ci)
- es-es-davefx/es-launch-ci-2: said “Arrancá la tercera tarea.”, heard “para la tefería.” (es), understood none (wanted launch:ci)
- es-es-davefx/es-launch-ci-3: said “Empezá la del runner.”, heard “Empezala del Gunaer” (es), understood launch:? (wanted launch:ci)
- es-es-davefx/es-launch-csv-2: said “Lanzá la segunda.”, heard “Lensar la segunda.” (es), understood none (wanted launch:csv)
- es-es-davefx/es-launch-csv-3: said “Dale con el CSV.”, heard “de Ale con el CSUB.” (es), understood none (wanted launch:csv)
- es-es-davefx/es-launch-reset-2: said “Arrancá la primera.”, heard “para encar la primera.” (es), understood none (wanted launch:reset)
- es-es-davefx/es-mute-1: said “Silencio.”, heard “See you in the next video.” (en), understood none (wanted mute)
- es-es-davefx/es-mute-2: said “Sacá el sonido.”, heard “Seca el sonido.” (es), understood none (wanted mute)
- es-es-davefx/es-mute-3: said “Callate un rato.”, heard “¡Hállate un plato!” (es), understood none (wanted mute)
- es-es-davefx/es-next-2: said “Pasá al próximo sprint.”, heard “hasta el próximo stream.” (es), understood none (wanted next)
- es-es-davefx/es-no-1: said “No.”, heard “Nope.” (en), understood none (wanted no)
- es-es-davefx/es-pause-1: said “Pausá.”, heard “Thank you for watching.” (en), understood none (wanted pause)
- es-es-davefx/es-pause-4: said “Poné pausa, por favor.”, heard “por favor” (es), understood none (wanted pause)
- es-es-davefx/es-recenter-2: said “Vení acá.”, heard “Leninaka.” (en), understood none (wanted recenter)
- es-es-davefx/es-reject-1: said “Devolvela.”, heard “de volvila.” (es), understood none (wanted reject)
- es-es-davefx/es-reject-3: said “No, rechazala.”, heard “No, pero te hazala.” (es), understood none (wanted reject)
- es-es-davefx/es-reject-5: said “Devuélvela al desarrollador.”, heard “de vuelve al desarrollador.” (es), understood none (wanted reject)
- es-es-davefx/es-reject-7: said “Rechazada.”, heard “Thank you.” (en), understood none (wanted reject)
- es-es-davefx/es-restart-1: said “Reiniciá.”, heard “Thank you.” (en), understood none (wanted restart)
- es-es-davefx/es-restart-2: said “Empezá de nuevo.”, heard “empezar del nuevo.” (es), understood launch:? (wanted restart)
- es-es-davefx/es-resume-1: said “Seguí.”, heard “City.” (en), understood none (wanted resume)
- es-es-davefx/es-resume-3: said “Reanudá el sprint.”, heard “y nos da el sprint.” (es), understood none (wanted resume)
- es-es-davefx/es-status-1: said “¿Cómo va?”, heard “Come on back.” (en), understood none (wanted status)
- es-es-davefx/es-unmute-1: said “Poné el sonido.”, heard “ponemos una vida.” (es), understood none (wanted unmute)
- es-es-davefx/es-unmute-2: said “Con sonido.”, heard “Conciñido.” (es), understood none (wanted unmute)
- es-es-davefx/es-yes-1: said “Sí.”, heard “See you.” (en), understood none (wanted yes)
- es-es-davefx/es-yes-2: said “Sí, dale.”, heard “See you.” (en), understood none (wanted yes)
- es-mx-claude/es-approve-1: said “Aprobá.”, heard “Aprovear” (es), understood none (wanted approve)
- es-mx-claude/es-approve-5: said “Apruebe la entrega, por favor.”, heard “Apreve la entrega, por favor.” (es), understood none (wanted approve)
- es-mx-claude/es-help-2: said “Ayuda.”, heard “and you're the” (en), understood none (wanted help)
- es-mx-claude/es-launch-ci-1: said “Lanzá la del CI.”, heard “Lanzala del C.” (es), understood launch:? (wanted launch:ci)
- es-mx-claude/es-launch-ci-2: said “Arrancá la tercera tarea.”, heard “Arancana Tecera Tarea” (en), understood none (wanted launch:ci)
- es-mx-claude/es-launch-csv-2: said “Lanzá la segunda.”, heard “Lansar la segunda” (es), understood none (wanted launch:csv)
- es-mx-claude/es-launch-csv-3: said “Dale con el CSV.”, heard “Dale con el CCB” (es), understood launch:? (wanted launch:csv)
- es-mx-claude/es-next-1: said “Siguiente sprint.”, heard “Siguiente splinter” (es), understood none (wanted next)
- es-mx-claude/es-pause-1: said “Pausá.”, heard “Vos se” (es), understood none (wanted pause)
- es-mx-claude/es-recenter-2: said “Vení acá.”, heard “Dení acá.” (es), understood none (wanted recenter)
- es-mx-claude/es-reject-1: said “Devolvela.”, heard “de Bolbella” (es), understood none (wanted reject)
- es-mx-claude/es-reject-3: said “No, rechazala.”, heard “No plecha sala.” (es), understood none (wanted reject)
- es-mx-claude/es-reject-5: said “Devuélvela al desarrollador.”, heard “de vuelve al desarrollador.” (es), understood none (wanted reject)
- es-mx-claude/es-reject-7: said “Rechazada.”, heard “De hecho, Sada.” (es), understood none (wanted reject)
- es-mx-claude/es-restart-1: said “Reiniciá.”, heard “¡Renicia!” (es), understood none (wanted restart)
- es-mx-claude/es-resume-1: said “Seguí.”, heard “CD.” (en), understood none (wanted resume)
- es-mx-claude/es-resume-3: said “Reanudá el sprint.”, heard “Renudal Sprint” (es), understood none (wanted resume)
- es-mx-claude/es-status-1: said “¿Cómo va?”, heard “Combo back.” (en), understood none (wanted status)
- es-mx-claude/es-unmute-2: said “Con sonido.”, heard “Consonatov” (en), understood none (wanted unmute)
- es-mx-claude/es-yes-1: said “Sí.”, heard “See you.” (en), understood none (wanted yes)

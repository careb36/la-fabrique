## whisper-tiny-detect-prompt

| language | phrases | commands right | WER | language right | s/phrase |
|---|---|---|---|---|---|
| en | 186 | 87% | 15.9% | 100% | 1.06 |
| es | 248 | 55% | 48.9% | 81% | 1.07 |
| all | 434 | 69% | 34.8% | 89% | 1.07 |

| voice | commands right | WER |
|---|---|---|
| en-heart | 95% | 8.7% |
| en-us-lessac | 89% | 13.4% |
| en-us-ryan | 77% | 25.6% |
| es-ar-daniela | 42% | 61.1% |
| es-dora | 65% | 48.1% |
| es-es-davefx | 47% | 51.1% |
| es-mx-claude | 66% | 35.3% |

| intent | es | en |
|---|---|---|
| approve | 32% | 76% |
| help | 33% | 89% |
| launch:ci | 42% | 89% |
| launch:csv | 42% | 89% |
| launch:reset | 58% | 100% |
| mute | 33% | 89% |
| next | 38% | 100% |
| no | 83% | 56% |
| none | 100% | 100% |
| pause | 75% | 92% |
| recenter | 50% | 100% |
| reject | 50% | 76% |
| restart | 25% | 89% |
| resume | 50% | 92% |
| status | 75% | 100% |
| unmute | 63% | 83% |
| yes | 81% | 83% |

Misses: 136

- en-heart/en-approve-4: said “Ship it.”, heard “Sheep it.” (en), understood none (wanted approve)
- en-heart/en-no-1: said “No.”, heard “Now.” (en), understood none (wanted no)
- en-heart/en-reject-4: said “This needs rework.”, heard “This needs to work.” (en), understood none (wanted reject)
- en-us-lessac/en-approve-4: said “Ship it.”, heard “Shippet.” (en), understood none (wanted approve)
- en-us-lessac/en-launch-ci-1: said “Launch the CI one.”, heard “Launch the C-dI1.” (en), understood launch:? (wanted launch:ci)
- en-us-lessac/en-launch-csv-3: said “Go ahead with the CSV.”, heard “Go ahead with the C-dashv.” (en), understood launch:? (wanted launch:csv)
- en-us-lessac/en-no-2: said “No, cancel that.”, heard “No. Can't solve that.” (en), understood none (wanted no)
- en-us-lessac/en-reject-4: said “This needs rework.”, heard “This needs to be worked.” (en), understood none (wanted reject)
- en-us-lessac/en-reject-7: said “Rejected.”, heard “Redicted.” (en), understood none (wanted reject)
- en-us-lessac/en-restart-1: said “Restart.”, heard “We start.” (en), understood launch:? (wanted restart)
- en-us-ryan/en-approve-1: said “Approve.”, heard “Improve.” (en), understood none (wanted approve)
- en-us-ryan/en-approve-2: said “Approve it.”, heard “I've proved it.” (en), understood none (wanted approve)
- en-us-ryan/en-approve-4: said “Ship it.”, heard “Shut that.” (en), understood none (wanted approve)
- en-us-ryan/en-help-2: said “Help.”, heard “Oh.” (en), understood none (wanted help)
- en-us-ryan/en-mute-1: said “Mute.”, heard “Watch.” (en), understood none (wanted mute)
- en-us-ryan/en-no-1: said “No.”, heard “Nope.” (en), understood none (wanted no)
- en-us-ryan/en-no-2: said “No, cancel that.”, heard “No. Can't select.” (en), understood none (wanted no)
- en-us-ryan/en-pause-1: said “Pause.”, heard “Oh yes.” (en), understood yes (wanted pause)
- en-us-ryan/en-reject-1: said “Send it back.”, heard “Center back.” (en), understood recenter (wanted reject)
- en-us-ryan/en-reject-4: said “This needs rework.”, heard “This needs to work.” (en), understood none (wanted reject)
- en-us-ryan/en-resume-1: said “Resume.”, heard “Wait a minute.” (en), understood pause (wanted resume)
- en-us-ryan/en-unmute-1: said “Unmute.”, heard “I'm mute.” (en), understood mute (wanted unmute)
- en-us-ryan/en-yes-1: said “Yes.”, heard “That's...” (en), understood none (wanted yes)
- en-us-ryan/en-yes-3: said “Confirmed.”, heard “Timbern.” (en), understood none (wanted yes)
- es-ar-daniela/es-approve-1: said “Aprobá.”, heard “¡Taprelo!” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-2: said “Aprobala.”, heard “Aprovala.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-3: said “Dale, aprobá la entrega.”, heard “Dale. Apóole.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-4: said “Está bien, apruebo.”, heard “Está bien.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-5: said “Apruebe la entrega, por favor.”, heard “Apliego el entrada. Por favor.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-7: said “Eh, sí, aprobado.”, heard “Es sí.” (es), understood none (wanted approve)
- es-ar-daniela/es-help-1: said “¿Qué puedo decir?”, heard “Dejalo.” (es), understood no (wanted help)
- es-ar-daniela/es-help-2: said “Ayuda.”, heard “I don't know.” (en), understood none (wanted help)
- es-ar-daniela/es-help-3: said “¿Qué órdenes entendés?”, heard “What do you want to understand this?” (en), understood none (wanted help)
- es-ar-daniela/es-launch-ci-1: said “Lanzá la del CI.”, heard “Lanzá.” (es), understood launch:? (wanted launch:ci)
- es-ar-daniela/es-launch-ci-2: said “Arrancá la tercera tarea.”, heard “Arrancále.” (es), understood launch:? (wanted launch:ci)
- es-ar-daniela/es-launch-csv-1: said “Lanzá la exportación CSV.”, heard “Lanzá.” (es), understood launch:? (wanted launch:csv)
- es-ar-daniela/es-launch-csv-3: said “Dale con el CSV.”, heard “Dale con ese.” (es), understood launch:? (wanted launch:csv)
- es-ar-daniela/es-launch-reset-2: said “Arrancá la primera.”, heard “Algo.” (es), understood none (wanted launch:reset)
- es-ar-daniela/es-launch-reset-3: said “Empezá con la de la contraseña.”, heard “Empezá con la de la contrasella.” (es), understood launch:? (wanted launch:reset)
- es-ar-daniela/es-mute-1: said “Silencio.”, heard “Ci.” (es), understood none (wanted mute)
- es-ar-daniela/es-mute-2: said “Sacá el sonido.”, heard “¿Sacales sonido?” (es), understood none (wanted mute)
- es-ar-daniela/es-mute-3: said “Callate un rato.”, heard “Que hayas de algún lado.” (es), understood none (wanted mute)
- es-ar-daniela/es-next-1: said “Siguiente sprint.”, heard “See you in the next video.” (en), understood none (wanted next)
- es-ar-daniela/es-next-2: said “Pasá al próximo sprint.”, heard “Pasal.” (es), understood none (wanted next)
- es-ar-daniela/es-pause-1: said “Pausá.”, heard “Okay.” (en), understood yes (wanted pause)
- es-ar-daniela/es-recenter-2: said “Vení acá.”, heard “What is this?” (en), understood none (wanted recenter)
- es-ar-daniela/es-recenter-3: said “Traé todo al frente.”, heard “Te estoy todo el frente.” (es), understood none (wanted recenter)
- es-ar-daniela/es-reject-1: said “Devolvela.”, heard “Te volve.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-3: said “No, rechazala.”, heard “No. Pichas sola.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-5: said “Devuélvela al desarrollador.”, heard “Te voy a la desarrajadora.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-6: said “No la apruebo, mandala de vuelta.”, heard “No lo puedo mandar la vuelta.” (es), understood launch:? (wanted reject)
- es-ar-daniela/es-reject-7: said “Rechazada.”, heard “That's it.” (en), understood none (wanted reject)
- es-ar-daniela/es-restart-1: said “Reiniciá.”, heard “Encia.” (es), understood none (wanted restart)
- es-ar-daniela/es-restart-3: said “Arrancá otra vez desde cero.”, heard “Algo.” (es), understood none (wanted restart)
- es-ar-daniela/es-resume-1: said “Seguí.”, heard “See you.” (en), understood none (wanted resume)
- es-ar-daniela/es-resume-3: said “Reanudá el sprint.”, heard “Then I'll spring.” (en), understood none (wanted resume)
- es-ar-daniela/es-status-1: said “¿Cómo va?”, heard “¿Cómo no es?” (es), understood none (wanted status)
- es-ar-daniela/es-unmute-2: said “Con sonido.”, heard “Continue.” (en), understood resume (wanted unmute)
- es-ar-daniela/es-yes-1: said “Sí.”, heard “Cheers.” (en), understood none (wanted yes)
- es-ar-daniela/es-yes-3: said “Confirmo.”, heard “Confiro.” (es), understood none (wanted yes)
- es-dora/es-approve-1: said “Aprobá.”, heard “Goodbye.” (en), understood none (wanted approve)
- es-dora/es-approve-3: said “Dale, aprobá la entrega.”, heard “Then.” (en), understood none (wanted approve)
- es-dora/es-approve-5: said “Apruebe la entrega, por favor.”, heard “Aprovea la entrega por favor.” (es), understood none (wanted approve)
- es-dora/es-approve-7: said “Eh, sí, aprobado.”, heard “Es si he probado.” (es), understood none (wanted approve)
- es-dora/es-help-1: said “¿Qué puedo decir?”, heard “What do they see?” (en), understood none (wanted help)
- es-dora/es-help-2: said “Ayuda.”, heard “I'll use that.” (en), understood none (wanted help)
- es-dora/es-launch-ci-1: said “Lanzá la del CI.”, heard “Launch.” (en), understood launch:? (wanted launch:ci)
- es-dora/es-launch-csv-3: said “Dale con el CSV.”, heard “Dale con el CSUB.” (es), understood launch:? (wanted launch:csv)
- es-dora/es-launch-reset-1: said “Lanzá el password reset.”, heard “Launch.” (en), understood launch:? (wanted launch:reset)
- es-dora/es-mute-1: said “Silencio.”, heard “See you later.” (en), understood none (wanted mute)
- es-dora/es-no-2: said “No, cancelá.”, heard “No canse la.” (es), understood none (wanted no)
- es-dora/es-pause-3: said “Esperá.”, heard “Spread.” (en), understood none (wanted pause)
- es-dora/es-recenter-2: said “Vení acá.”, heard “Benika.” (en), understood none (wanted recenter)
- es-dora/es-reject-3: said “No, rechazala.”, heard “No. Rechasala.” (es), understood none (wanted reject)
- es-dora/es-reject-5: said “Devuélvela al desarrollador.”, heard “Te vuelve la desarrollador.” (es), understood none (wanted reject)
- es-dora/es-reject-7: said “Rechazada.”, heard “Precha salda.” (es), understood none (wanted reject)
- es-dora/es-restart-1: said “Reiniciá.”, heard “Reignis.” (en), understood none (wanted restart)
- es-dora/es-restart-2: said “Empezá de nuevo.”, heard “In person, the new.” (en), understood none (wanted restart)
- es-dora/es-resume-1: said “Seguí.”, heard “Okay.” (en), understood yes (wanted resume)
- es-dora/es-resume-3: said “Reanudá el sprint.”, heard “Preno Dale.” (es), understood none (wanted resume)
- es-dora/es-status-1: said “¿Cómo va?”, heard “Come on back.” (en), understood none (wanted status)
- es-dora/es-yes-1: said “Sí.”, heard “Say it.” (en), understood none (wanted yes)
- es-es-davefx/es-approve-1: said “Aprobá.”, heard “Okay.” (en), understood yes (wanted approve)
- es-es-davefx/es-approve-2: said “Aprobala.”, heard “Revala.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-3: said “Dale, aprobá la entrega.”, heard “Dale. Aprovea la entrega.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-4: said “Está bien, apruebo.”, heard “Está bien. Aprovebo.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-5: said “Apruebe la entrega, por favor.”, heard “No probé de la entrada. Por favor.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-6: said “Me parece bien, aceptala.”, heard “Me parece bien.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-7: said “Eh, sí, aprobado.”, heard “Es.” (es), understood none (wanted approve)
- es-es-davefx/es-help-1: said “¿Qué puedo decir?”, heard “Okay.” (en), understood yes (wanted help)
- es-es-davefx/es-help-2: said “Ayuda.”, heard “Thank you.” (en), understood none (wanted help)
- es-es-davefx/es-launch-ci-1: said “Lanzá la del CI.”, heard “Lanzá. Adelante.” (es), understood launch:? (wanted launch:ci)
- es-es-davefx/es-launch-ci-2: said “Arrancá la tercera tarea.”, heard “Alancar la tercera.” (es), understood none (wanted launch:ci)
- es-es-davefx/es-launch-ci-3: said “Empezá la del runner.”, heard “Empezá la delgoamer.” (es), understood launch:? (wanted launch:ci)
- es-es-davefx/es-launch-csv-1: said “Lanzá la exportación CSV.”, heard “Lanzá.” (es), understood launch:? (wanted launch:csv)
- es-es-davefx/es-launch-csv-3: said “Dale con el CSV.”, heard “Dale con el CSUB.” (es), understood launch:? (wanted launch:csv)
- es-es-davefx/es-launch-reset-2: said “Arrancá la primera.”, heard “Al primer.” (es), understood none (wanted launch:reset)
- es-es-davefx/es-mute-1: said “Silencio.”, heard “C-Lensio.” (en), understood none (wanted mute)
- es-es-davefx/es-mute-2: said “Sacá el sonido.”, heard “Seca el sonido.” (es), understood none (wanted mute)
- es-es-davefx/es-mute-3: said “Callate un rato.”, heard “Adé.” (es), understood none (wanted mute)
- es-es-davefx/es-next-1: said “Siguiente sprint.”, heard “Siéntese sprint.” (es), understood none (wanted next)
- es-es-davefx/es-next-2: said “Pasá al próximo sprint.”, heard “La próxima.” (es), understood none (wanted next)
- es-es-davefx/es-no-1: said “No.”, heard “Nope.” (en), understood none (wanted no)
- es-es-davefx/es-pause-1: said “Pausá.”, heard “Okay.” (en), understood yes (wanted pause)
- es-es-davefx/es-recenter-1: said “Centrá los paneles.”, heard “Entrar los paneles.” (es), understood none (wanted recenter)
- es-es-davefx/es-recenter-2: said “Vení acá.”, heard “Vení.” (es), understood none (wanted recenter)
- es-es-davefx/es-reject-3: said “No, rechazala.”, heard “No.” (es), understood no (wanted reject)
- es-es-davefx/es-reject-5: said “Devuélvela al desarrollador.”, heard “De buen bela al desarrollador.” (es), understood none (wanted reject)
- es-es-davefx/es-reject-7: said “Rechazada.”, heard “Dejalo.” (es), understood no (wanted reject)
- es-es-davefx/es-restart-1: said “Reiniciá.”, heard “Thank you.” (en), understood none (wanted restart)
- es-es-davefx/es-restart-2: said “Empezá de nuevo.”, heard “Empezate el nuevo.” (es), understood launch:? (wanted restart)
- es-es-davefx/es-resume-1: said “Seguí.”, heard “Okay.” (en), understood yes (wanted resume)
- es-es-davefx/es-resume-3: said “Reanudá el sprint.”, heard “Real nos da el sprint.” (es), understood none (wanted resume)
- es-es-davefx/es-status-1: said “¿Cómo va?”, heard “Good.” (en), understood none (wanted status)
- es-es-davefx/es-unmute-1: said “Poné el sonido.”, heard “Boné.” (es), understood none (wanted unmute)
- es-mx-claude/es-approve-4: said “Está bien, apruebo.”, heard “Está bien. Aproevo.” (es), understood none (wanted approve)
- es-mx-claude/es-approve-5: said “Apruebe la entrega, por favor.”, heard “Aprovele la entrega. Por favor.” (es), understood none (wanted approve)
- es-mx-claude/es-help-2: said “Ayuda.”, heard “And you're there.” (en), understood none (wanted help)
- es-mx-claude/es-launch-ci-1: said “Lanzá la del CI.”, heard “Lanzá la del C.” (es), understood launch:? (wanted launch:ci)
- es-mx-claude/es-launch-csv-1: said “Lanzá la exportación CSV.”, heard “Lanzá.” (es), understood launch:? (wanted launch:csv)
- es-mx-claude/es-launch-csv-3: said “Dale con el CSV.”, heard “Dale con el CCB.” (es), understood launch:? (wanted launch:csv)
- es-mx-claude/es-launch-reset-1: said “Lanzá el password reset.”, heard “Launch.” (en), understood launch:? (wanted launch:reset)
- es-mx-claude/es-mute-3: said “Callate un rato.”, heard “Cajate. Vuntrato.” (es), understood none (wanted mute)
- es-mx-claude/es-next-1: said “Siguiente sprint.”, heard “Segentes.” (es), understood none (wanted next)
- es-mx-claude/es-pause-1: said “Pausá.”, heard “Go.” (en), understood none (wanted pause)
- es-mx-claude/es-recenter-2: said “Vení acá.”, heard “De Ni Aka.” (en), understood none (wanted recenter)
- es-mx-claude/es-reject-3: said “No, rechazala.”, heard “No.” (es), understood no (wanted reject)
- es-mx-claude/es-reject-5: said “Devuélvela al desarrollador.”, heard “Debo el delal de desarrollador.” (es), understood none (wanted reject)
- es-mx-claude/es-reject-7: said “Rechazada.”, heard “Dejalo.” (es), understood no (wanted reject)
- es-mx-claude/es-restart-1: said “Reiniciá.”, heard “Reyes.” (es), understood none (wanted restart)
- es-mx-claude/es-restart-2: said “Empezá de nuevo.”, heard “Empezate nuevo.” (es), understood launch:? (wanted restart)
- es-mx-claude/es-restart-3: said “Arrancá otra vez desde cero.”, heard “Arrancá. Votra vez de 0.” (es), understood launch:? (wanted restart)
- es-mx-claude/es-resume-1: said “Seguí.”, heard “Sv.” (en), understood none (wanted resume)
- es-mx-claude/es-resume-3: said “Reanudá el sprint.”, heard “Realenuda el sprint.” (es), understood none (wanted resume)
- es-mx-claude/es-status-1: said “¿Cómo va?”, heard “Come over there.” (en), understood none (wanted status)
- es-mx-claude/es-unmute-2: said “Con sonido.”, heard “Control.” (en), understood none (wanted unmute)

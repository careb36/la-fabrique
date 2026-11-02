## fw-large-v3-turbo

| language | phrases | commands right | WER | language right | s/phrase |
|---|---|---|---|---|---|
| en | 186 | 91% | 10.1% | 99% | 18.74 |
| es | 183 | 74% | 29.3% | 86% | 10.26 |
| all | 369 | 83% | 19.6% | 93% | 14.54 |

| voice | commands right | WER |
|---|---|---|
| en-heart | 100% | 3.9% |
| en-us-lessac | 92% | 6.7% |
| en-us-ryan | 82% | 19.6% |
| es-ar-daniela | 60% | 38.6% |
| es-dora | 85% | 22.0% |
| es-es-davefx | 78% | 27.1% |

| intent | es | en |
|---|---|---|
| approve | 52% | 90% |
| help | 89% | 89% |
| launch:ci | 44% | 78% |
| launch:csv | 78% | 78% |
| launch:reset | 78% | 100% |
| mute | 89% | 89% |
| next | 83% | 100% |
| no | 67% | 89% |
| none | 100% | 100% |
| pause | 75% | 83% |
| recenter | 78% | 100% |
| reject | 76% | 100% |
| restart | 78% | 100% |
| resume | 67% | 92% |
| status | 83% | 100% |
| unmute | 83% | 67% |
| yes | 67% | 83% |

Misses: 63

- en-us-lessac/en-approve-4: said “Ship it.”, heard “Chip it.” (en), understood none (wanted approve)
- en-us-lessac/en-launch-ci-1: said “Launch the CI one.”, heard “Launch the CDI-1.” (en), understood launch:? (wanted launch:ci)
- en-us-lessac/en-launch-csv-3: said “Go ahead with the CSV.”, heard “Go ahead with the CDESV.” (en), understood launch:? (wanted launch:csv)
- en-us-lessac/en-pause-4: said “Pause it, please.”, heard “deposit, please.” (en), understood none (wanted pause)
- en-us-lessac/en-unmute-1: said “Unmute.”, heard “A mute” (en), understood mute (wanted unmute)
- en-us-ryan/en-approve-4: said “Ship it.”, heard “Shut it.” (en), understood none (wanted approve)
- en-us-ryan/en-help-2: said “Help.”, heard “Oh!” (en), understood none (wanted help)
- en-us-ryan/en-launch-ci-1: said “Launch the CI one.”, heard “Lunch the CI won.” (en), understood none (wanted launch:ci)
- en-us-ryan/en-launch-csv-1: said “Launch the CSV export.”, heard “Lunge to see as we export.” (en), understood none (wanted launch:csv)
- en-us-ryan/en-mute-1: said “Mute.”, heard “Woes!” (en), understood none (wanted mute)
- en-us-ryan/en-no-1: said “No.”, heard “Well,” (en), understood none (wanted no)
- en-us-ryan/en-pause-1: said “Pause.”, heard “Always.” (en), understood none (wanted pause)
- en-us-ryan/en-resume-1: said “Resume.”, heard “Oui, c'est bon.” (fr), understood none (wanted resume)
- en-us-ryan/en-unmute-1: said “Unmute.”, heard “I'm mute.” (en), understood mute (wanted unmute)
- en-us-ryan/en-yes-1: said “Yes.”, heard “Nests.” (en), understood none (wanted yes)
- en-us-ryan/en-yes-3: said “Confirmed.”, heard “Pam Verne.” (en), understood none (wanted yes)
- es-ar-daniela/es-approve-3: said “Dale, aprobá la entrega.”, heard “Dale, tapo a la entrega.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-4: said “Está bien, apruebo.”, heard “Está bien, la pruebo.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-5: said “Apruebe la entrega, por favor.”, heard “Aprove la entrega, por favor.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-7: said “Eh, sí, aprobado.”, heard “Así, te abrodo.” (es), understood none (wanted approve)
- es-ar-daniela/es-help-2: said “Ayuda.”, heard “Arudó.” (es), understood none (wanted help)
- es-ar-daniela/es-launch-ci-1: said “Lanzá la del CI.”, heard “La ensalada de C.I.” (es), understood none (wanted launch:ci)
- es-ar-daniela/es-launch-ci-3: said “Empezá la del runner.”, heard “Empezá la del runar.” (es), understood launch:? (wanted launch:ci)
- es-ar-daniela/es-launch-csv-2: said “Lanzá la segunda.”, heard “la ensalada segunda.” (es), understood none (wanted launch:csv)
- es-ar-daniela/es-launch-csv-3: said “Dale con el CSV.”, heard “Dale con SSB.” (es), understood launch:? (wanted launch:csv)
- es-ar-daniela/es-launch-reset-3: said “Empezá con la de la contraseña.”, heard “Empezá con la de la contracera” (es), understood launch:? (wanted launch:reset)
- es-ar-daniela/es-mute-1: said “Silencio.”, heard “Siguiente.” (es), understood next (wanted mute)
- es-ar-daniela/es-no-1: said “No.”, heard “な。” (ja), understood none (wanted no)
- es-ar-daniela/es-no-3: said “Mejor no, dejalo.”, heard “Mejor notéjalo.” (es), understood none (wanted no)
- es-ar-daniela/es-pause-1: said “Pausá.”, heard “Có sao?” (vi), understood none (wanted pause)
- es-ar-daniela/es-recenter-3: said “Traé todo al frente.”, heard “Te doy todo el frente.” (es), understood none (wanted recenter)
- es-ar-daniela/es-reject-1: said “Devolvela.”, heard “Teorvela.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-3: said “No, rechazala.”, heard “No es pechazala.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-5: said “Devuélvela al desarrollador.”, heard “Te huele al desarrollador.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-7: said “Rechazada.”, heard “hechas hada.” (es), understood none (wanted reject)
- es-ar-daniela/es-restart-1: said “Reiniciá.”, heard “Эйнисия!” (ru), understood none (wanted restart)
- es-ar-daniela/es-resume-1: said “Seguí.”, heard “See.” (en), understood none (wanted resume)
- es-ar-daniela/es-resume-3: said “Reanudá el sprint.”, heard “Tenlo al sprint.” (es), understood none (wanted resume)
- es-ar-daniela/es-status-1: said “¿Cómo va?”, heard “Como a.” (es), understood none (wanted status)
- es-ar-daniela/es-unmute-2: said “Con sonido.”, heard “Consenia.” (ca), understood none (wanted unmute)
- es-ar-daniela/es-yes-1: said “Sí.”, heard “谢谢” (zh), understood none (wanted yes)
- es-dora/es-approve-2: said “Aprobala.”, heard “Aprová-la.” (pt), understood none (wanted approve)
- es-dora/es-approve-3: said “Dale, aprobá la entrega.”, heard “Dale a probar la entrega.” (es), understood none (wanted approve)
- es-dora/es-launch-ci-1: said “Lanzá la del CI.”, heard “L'ansala del 6” (it), understood none (wanted launch:ci)
- es-dora/es-launch-reset-2: said “Arrancá la primera.”, heard “Arrencar la primera.” (ca), understood none (wanted launch:reset)
- es-dora/es-pause-1: said “Pausá.”, heard “Bowsack.” (en), understood none (wanted pause)
- es-dora/es-reject-7: said “Rechazada.”, heard “Prechaçada.” (pt), understood none (wanted reject)
- es-dora/es-resume-1: said “Seguí.”, heard “Саги.” (ru), understood none (wanted resume)
- es-dora/es-status-1: said “¿Cómo va?”, heard “Come on, bye.” (en), understood none (wanted status)
- es-dora/es-yes-1: said “Sí.”, heard “See if I-” (en), understood none (wanted yes)
- es-es-davefx/es-approve-1: said “Aprobá.”, heard “バイバイ” (ja), understood none (wanted approve)
- es-es-davefx/es-approve-2: said “Aprobala.”, heard “¡Arrebala!” (es), understood none (wanted approve)
- es-es-davefx/es-approve-5: said “Apruebe la entrega, por favor.”, heard “No pruebe la entreta, por favor.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-7: said “Eh, sí, aprobado.”, heard “Te sí, te ha probado.” (es), understood none (wanted approve)
- es-es-davefx/es-launch-ci-1: said “Lanzá la del CI.”, heard “Lanzala del CEI.” (es), understood launch:? (wanted launch:ci)
- es-es-davefx/es-launch-ci-3: said “Empezá la del runner.”, heard “Empezar a la delgomear.” (es), understood launch:? (wanted launch:ci)
- es-es-davefx/es-next-2: said “Pasá al próximo sprint.”, heard “pasará el próximo Spring.” (es), understood none (wanted next)
- es-es-davefx/es-no-1: said “No.”, heard “またね。” (ja), understood none (wanted no)
- es-es-davefx/es-pause-1: said “Pausá.”, heard “Это все.” (ru), understood none (wanted pause)
- es-es-davefx/es-recenter-1: said “Centrá los paneles.”, heard “entrar a los paneles.” (es), understood none (wanted recenter)
- es-es-davefx/es-restart-1: said “Reiniciá.”, heard “inicia” (es), understood launch:? (wanted restart)
- es-es-davefx/es-resume-1: said “Seguí.”, heard “Sing it.” (en), understood none (wanted resume)
- es-es-davefx/es-yes-1: said “Sí.”, heard “Team.” (en), understood none (wanted yes)

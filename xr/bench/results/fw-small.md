## fw-small

| language | phrases | commands right | WER | language right | s/phrase |
|---|---|---|---|---|---|
| en | 186 | 90% | 9.6% | 100% | 3.38 |
| es | 248 | 65% | 37.6% | 81% | 3.82 |
| all | 434 | 76% | 25.6% | 89% | 3.63 |

| voice | commands right | WER |
|---|---|---|
| en-heart | 98% | 4.7% |
| en-us-lessac | 90% | 7.4% |
| en-us-ryan | 82% | 16.8% |
| es-ar-daniela | 56% | 45.7% |
| es-dora | 73% | 29.9% |
| es-es-davefx | 58% | 43.8% |
| es-mx-claude | 73% | 31.0% |

| intent | es | en |
|---|---|---|
| approve | 50% | 81% |
| help | 58% | 89% |
| launch:ci | 25% | 78% |
| launch:csv | 58% | 78% |
| launch:reset | 75% | 100% |
| mute | 92% | 89% |
| next | 88% | 100% |
| no | 83% | 100% |
| none | 100% | 100% |
| pause | 63% | 75% |
| recenter | 67% | 100% |
| reject | 54% | 100% |
| restart | 58% | 100% |
| resume | 69% | 100% |
| status | 75% | 92% |
| unmute | 75% | 67% |
| yes | 50% | 83% |

Misses: 105

- en-heart/en-pause-1: said “Pause.”, heard “Paws.” (en), understood none (wanted pause)
- en-us-lessac/en-approve-4: said “Ship it.”, heard “Chip it.” (en), understood none (wanted approve)
- en-us-lessac/en-launch-ci-1: said “Launch the CI one.”, heard “Launch the CDI-1.” (en), understood launch:? (wanted launch:ci)
- en-us-lessac/en-launch-csv-3: said “Go ahead with the CSV.”, heard “Go ahead with the CDES-V.” (en), understood launch:? (wanted launch:csv)
- en-us-lessac/en-pause-4: said “Pause it, please.”, heard “deposit, please.” (en), understood none (wanted pause)
- en-us-lessac/en-status-2: said “How are we doing on the sprint?”, heard “How were we doing on the sprint?” (en), understood none (wanted status)
- en-us-lessac/en-unmute-1: said “Unmute.”, heard “a mute” (en), understood mute (wanted unmute)
- en-us-ryan/en-approve-1: said “Approve.”, heard “Adbrew!” (en), understood none (wanted approve)
- en-us-ryan/en-approve-2: said “Approve it.”, heard “I'd prune it.” (en), understood none (wanted approve)
- en-us-ryan/en-approve-4: said “Ship it.”, heard “Shut that.” (en), understood none (wanted approve)
- en-us-ryan/en-help-2: said “Help.”, heard “Oh!” (en), understood none (wanted help)
- en-us-ryan/en-launch-ci-1: said “Launch the CI one.”, heard “Lunch the C.I. One.” (en), understood none (wanted launch:ci)
- en-us-ryan/en-launch-csv-1: said “Launch the CSV export.”, heard “Lunge the CSV export.” (en), understood none (wanted launch:csv)
- en-us-ryan/en-mute-1: said “Mute.”, heard “Close!” (en), understood none (wanted mute)
- en-us-ryan/en-pause-1: said “Pause.”, heard “Oh, yes.” (en), understood yes (wanted pause)
- en-us-ryan/en-unmute-1: said “Unmute.”, heard “I'm mute.” (en), understood mute (wanted unmute)
- en-us-ryan/en-yes-1: said “Yes.”, heard “NASA's” (en), understood none (wanted yes)
- en-us-ryan/en-yes-3: said “Confirmed.”, heard “Tim Verne” (en), understood none (wanted yes)
- es-ar-daniela/es-approve-1: said “Aprobá.”, heard “¡Tá proba!” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-3: said “Dale, aprobá la entrega.”, heard “de alias tapó a la entrega.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-4: said “Está bien, apruebo.”, heard “Está bien, la pruebo.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-5: said “Apruebe la entrega, por favor.”, heard “Aprovele la entidad, por favor.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-7: said “Eh, sí, aprobado.”, heard “y si te ha probado.” (es), understood none (wanted approve)
- es-ar-daniela/es-help-1: said “¿Qué puedo decir?”, heard “te pueda vacir.” (es), understood none (wanted help)
- es-ar-daniela/es-help-2: said “Ayuda.”, heard “¡Adiós!” (es), understood none (wanted help)
- es-ar-daniela/es-launch-ci-1: said “Lanzá la del CI.”, heard “la en sala de SEI.” (es), understood none (wanted launch:ci)
- es-ar-daniela/es-launch-ci-3: said “Empezá la del runner.”, heard “Empecé a la del runar.” (es), understood none (wanted launch:ci)
- es-ar-daniela/es-launch-csv-1: said “Lanzá la exportación CSV.”, heard “Lensar la equipotación CSV.” (es), understood none (wanted launch:csv)
- es-ar-daniela/es-launch-csv-2: said “Lanzá la segunda.”, heard “la en sala segunda.” (es), understood none (wanted launch:csv)
- es-ar-daniela/es-launch-csv-3: said “Dale con el CSV.”, heard “Dale con ese S.O.A.” (es), understood launch:? (wanted launch:csv)
- es-ar-daniela/es-launch-reset-1: said “Lanzá el password reset.”, heard “la ensalpa sobre receta.” (es), understood none (wanted launch:reset)
- es-ar-daniela/es-launch-reset-3: said “Empezá con la de la contraseña.”, heard “Empezar con la de la contrasella.” (es), understood launch:? (wanted launch:reset)
- es-ar-daniela/es-pause-1: said “Pausá.”, heard “Go son.” (en), understood none (wanted pause)
- es-ar-daniela/es-recenter-2: said “Vení acá.”, heard “デニアカ” (ja), understood none (wanted recenter)
- es-ar-daniela/es-recenter-3: said “Traé todo al frente.”, heard “De todo el frente.” (es), understood none (wanted recenter)
- es-ar-daniela/es-reject-1: said “Devolvela.”, heard “te volvela.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-3: said “No, rechazala.”, heard “¡Nuevas pechas a la!” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-5: said “Devuélvela al desarrollador.”, heard “Te huele al desarrollador.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-7: said “Rechazada.”, heard “Hechazada.” (es), understood none (wanted reject)
- es-ar-daniela/es-restart-1: said “Reiniciá.”, heard “e inicia.” (pt), understood launch:? (wanted restart)
- es-ar-daniela/es-resume-1: said “Seguí.”, heard “See you.” (en), understood none (wanted resume)
- es-ar-daniela/es-resume-3: said “Reanudá el sprint.”, heard “Tenlo al sprint.” (es), understood none (wanted resume)
- es-ar-daniela/es-status-1: said “¿Cómo va?”, heard “Какой?” (ru), understood none (wanted status)
- es-ar-daniela/es-yes-1: said “Sí.”, heard “See ya.” (en), understood none (wanted yes)
- es-ar-daniela/es-yes-3: said “Confirmo.”, heard “Confirgo.” (es), understood none (wanted yes)
- es-dora/es-approve-1: said “Aprobá.”, heard “É probado!” (pt), understood none (wanted approve)
- es-dora/es-approve-2: said “Aprobala.”, heard “É PROBALA!” (pt), understood none (wanted approve)
- es-dora/es-approve-3: said “Dale, aprobá la entrega.”, heard “Dall'approbata intrega” (it), understood none (wanted approve)
- es-dora/es-help-2: said “Ayuda.”, heard “I knew that.” (en), understood none (wanted help)
- es-dora/es-launch-ci-1: said “Lanzá la del CI.”, heard “لنسأل الدلسي” (ar), understood none (wanted launch:ci)
- es-dora/es-launch-ci-3: said “Empezá la del runner.”, heard “Empezá la del runer.” (es), understood launch:? (wanted launch:ci)
- es-dora/es-launch-csv-3: said “Dale con el CSV.”, heard “Dalle con il CSV.” (it), understood none (wanted launch:csv)
- es-dora/es-pause-1: said “Pausá.”, heard “Bowsack!” (en), understood none (wanted pause)
- es-dora/es-pause-3: said “Esperá.”, heard “Espadr” (en), understood none (wanted pause)
- es-dora/es-recenter-2: said “Vení acá.”, heard “Beniyakar.” (en), understood none (wanted recenter)
- es-dora/es-reject-5: said “Devuélvela al desarrollador.”, heard “te vuélvela al desarrollador.” (es), understood none (wanted reject)
- es-dora/es-reject-7: said “Rechazada.”, heard “Prechaçada!” (pt), understood none (wanted reject)
- es-dora/es-restart-1: said “Reiniciá.”, heard “Rainicia.” (en), understood none (wanted restart)
- es-dora/es-resume-1: said “Seguí.”, heard “Saguei!” (pt), understood none (wanted resume)
- es-dora/es-status-1: said “¿Cómo va?”, heard “Come on, man.” (en), understood none (wanted status)
- es-dora/es-yes-1: said “Sí.”, heard “See you.” (en), understood none (wanted yes)
- es-dora/es-yes-3: said “Confirmo.”, heard “Konfirma.” (sv), understood none (wanted yes)
- es-es-davefx/es-approve-1: said “Aprobá.”, heard “Rr!” (en), understood none (wanted approve)
- es-es-davefx/es-approve-2: said “Aprobala.”, heard “¡Arriba la!” (es), understood none (wanted approve)
- es-es-davefx/es-approve-3: said “Dale, aprobá la entrega.”, heard “Dale a probar la entrega.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-5: said “Apruebe la entrega, por favor.”, heard “No probar de la entretas, por favor.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-7: said “Eh, sí, aprobado.”, heard “Te sí, te ha probado.” (es), understood none (wanted approve)
- es-es-davefx/es-help-2: said “Ayuda.”, heard “Pay you then.” (en), understood none (wanted help)
- es-es-davefx/es-launch-ci-1: said “Lanzá la del CI.”, heard “¡Lanzar la del SEI!” (es), understood launch:? (wanted launch:ci)
- es-es-davefx/es-launch-ci-2: said “Arrancá la tercera tarea.”, heard “Akan kala terseret ada dia.” (id), understood none (wanted launch:ci)
- es-es-davefx/es-launch-ci-3: said “Empezá la del runner.”, heard “Empezala del Gomer.” (es), understood launch:? (wanted launch:ci)
- es-es-davefx/es-launch-csv-3: said “Dale con el CSV.”, heard “Ya le con el CSV.” (es), understood none (wanted launch:csv)
- es-es-davefx/es-mute-2: said “Sacá el sonido.”, heard “Se cae el sonido.” (es), understood none (wanted mute)
- es-es-davefx/es-no-1: said “No.”, heard “Nope.” (en), understood none (wanted no)
- es-es-davefx/es-pause-1: said “Pausá.”, heard “¡Muchas gracias!” (es), understood none (wanted pause)
- es-es-davefx/es-pause-4: said “Poné pausa, por favor.”, heard “Pone pasa, por favor.” (es), understood none (wanted pause)
- es-es-davefx/es-recenter-2: said “Vení acá.”, heard “Venine a casa” (it), understood none (wanted recenter)
- es-es-davefx/es-reject-1: said “Devolvela.”, heard “de volvela.” (es), understood none (wanted reject)
- es-es-davefx/es-reject-2: said “Mandala de vuelta.”, heard “mande a la devuelta.” (es), understood none (wanted reject)
- es-es-davefx/es-reject-3: said “No, rechazala.”, heard “No, pero te ha salido.” (es), understood none (wanted reject)
- es-es-davefx/es-reject-7: said “Rechazada.”, heard “Te he chasada” (es), understood none (wanted reject)
- es-es-davefx/es-restart-1: said “Reiniciá.”, heard “de inicia.” (es), understood launch:? (wanted restart)
- es-es-davefx/es-restart-2: said “Empezá de nuevo.”, heard “Empezad en nuevo.” (es), understood launch:? (wanted restart)
- es-es-davefx/es-resume-1: said “Seguí.”, heard “See you.” (en), understood none (wanted resume)
- es-es-davefx/es-status-1: said “¿Cómo va?”, heard “Кома-ба!” (ru), understood none (wanted status)
- es-es-davefx/es-unmute-2: said “Con sonido.”, heard “con sanito.” (es), understood none (wanted unmute)
- es-es-davefx/es-yes-1: said “Sí.”, heard “See you.” (en), understood none (wanted yes)
- es-es-davefx/es-yes-2: said “Sí, dale.”, heard “See you, darling.” (en), understood none (wanted yes)
- es-mx-claude/es-approve-1: said “Aprobá.”, heard “Aprova.” (es), understood none (wanted approve)
- es-mx-claude/es-help-2: said “Ayuda.”, heard “and you'll die.” (en), understood none (wanted help)
- es-mx-claude/es-launch-ci-1: said “Lanzá la del CI.”, heard “La En sala del C.I.” (es), understood none (wanted launch:ci)
- es-mx-claude/es-launch-ci-3: said “Empezá la del runner.”, heard “Empezá la del Runer.” (es), understood launch:? (wanted launch:ci)
- es-mx-claude/es-launch-reset-1: said “Lanzá el password reset.”, heard “Lançar el password recets.” (ca), understood none (wanted launch:reset)
- es-mx-claude/es-next-1: said “Siguiente sprint.”, heard “Siguiente Splinter” (es), understood none (wanted next)
- es-mx-claude/es-no-1: said “No.”, heard “North.” (en), understood none (wanted no)
- es-mx-claude/es-pause-1: said “Pausá.”, heard “BOSA” (en), understood none (wanted pause)
- es-mx-claude/es-reject-1: said “Devolvela.”, heard “de volvela.” (es), understood none (wanted reject)
- es-mx-claude/es-reject-2: said “Mandala de vuelta.”, heard “manda la devuelta” (es), understood launch:? (wanted reject)
- es-mx-claude/es-reject-3: said “No, rechazala.”, heard “No decha sala.” (es), understood none (wanted reject)
- es-mx-claude/es-restart-1: said “Reiniciá.”, heard “RENICIA” (it), understood none (wanted restart)
- es-mx-claude/es-resume-1: said “Seguí.”, heard “Salih.” (en), understood none (wanted resume)
- es-mx-claude/es-status-1: said “¿Cómo va?”, heard “¡Comoda!” (es), understood none (wanted status)
- es-mx-claude/es-unmute-2: said “Con sonido.”, heard “con Sonidos.” (es), understood none (wanted unmute)
- es-mx-claude/es-yes-1: said “Sí.”, heard “Sive.” (fr), understood none (wanted yes)
- es-mx-claude/es-yes-4: said “Exacto, hacelo.”, heard “Εξάπτω θα σέλω.” (el), understood none (wanted yes)

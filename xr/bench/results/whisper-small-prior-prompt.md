## whisper-small-prior-prompt

| language | phrases | commands right | WER | language right | s/phrase |
|---|---|---|---|---|---|
| en | 186 | 94% | 7.7% | 100% | 3.02 |
| es | 248 | 75% | 26.1% | 88% | 2.95 |
| all | 434 | 83% | 18.2% | 93% | 2.98 |

| voice | commands right | WER |
|---|---|---|
| en-heart | 100% | 1.7% |
| en-us-lessac | 97% | 3.7% |
| en-us-ryan | 84% | 17.7% |
| es-ar-daniela | 63% | 35.4% |
| es-dora | 81% | 27.4% |
| es-es-davefx | 71% | 24.8% |
| es-mx-claude | 85% | 16.8% |

| intent | es | en |
|---|---|---|
| approve | 50% | 86% |
| help | 75% | 89% |
| launch:ci | 50% | 78% |
| launch:csv | 92% | 89% |
| launch:reset | 100% | 100% |
| mute | 83% | 89% |
| next | 75% | 100% |
| no | 100% | 100% |
| none | 100% | 100% |
| pause | 69% | 83% |
| recenter | 75% | 100% |
| reject | 61% | 100% |
| restart | 83% | 100% |
| resume | 69% | 100% |
| status | 94% | 100% |
| unmute | 88% | 100% |
| yes | 63% | 83% |

Misses: 74

- en-us-lessac/en-approve-4: said “Ship it.”, heard “Chip it.” (en), understood none (wanted approve)
- en-us-lessac/en-launch-ci-1: said “Launch the CI one.”, heard “Launch the CDI-1.” (en), understood launch:? (wanted launch:ci)
- en-us-ryan/en-approve-1: said “Approve.”, heard “Unbrew.” (en), understood none (wanted approve)
- en-us-ryan/en-approve-4: said “Ship it.”, heard “Shut that.” (en), understood none (wanted approve)
- en-us-ryan/en-help-2: said “Help.”, heard “Oh.” (en), understood none (wanted help)
- en-us-ryan/en-launch-ci-1: said “Launch the CI one.”, heard “Lumps.” (en), understood none (wanted launch:ci)
- en-us-ryan/en-launch-csv-1: said “Launch the CSV export.”, heard “Lunge. This is the export.” (en), understood none (wanted launch:csv)
- en-us-ryan/en-mute-1: said “Mute.”, heard “Close.” (en), understood none (wanted mute)
- en-us-ryan/en-pause-1: said “Pause.”, heard “How is.” (en), understood none (wanted pause)
- en-us-ryan/en-pause-3: said “Wait.”, heard “What.” (en), understood none (wanted pause)
- en-us-ryan/en-yes-1: said “Yes.”, heard “Next.” (en), understood next (wanted yes)
- en-us-ryan/en-yes-3: said “Confirmed.”, heard “TempVern.” (en), understood none (wanted yes)
- es-ar-daniela/es-approve-1: said “Aprobá.”, heard “La prueba.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-3: said “Dale, aprobá la entrega.”, heard “Dale.” (es), understood yes (wanted approve)
- es-ar-daniela/es-approve-4: said “Está bien, apruebo.”, heard “Está bien. La prueba.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-5: said “Apruebe la entrega, por favor.”, heard “Apluede la entidad por favor.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-7: said “Eh, sí, aprobado.”, heard “Así.” (es), understood none (wanted approve)
- es-ar-daniela/es-help-1: said “¿Qué puedo decir?”, heard “Te puedo decir.” (es), understood none (wanted help)
- es-ar-daniela/es-help-2: said “Ayuda.”, heard “Arrancá.” (es), understood launch:? (wanted help)
- es-ar-daniela/es-launch-ci-1: said “Lanzá la del CI.”, heard “La ensalada de CI.” (es), understood none (wanted launch:ci)
- es-ar-daniela/es-launch-ci-3: said “Empezá la del runner.”, heard “Empezá la del runar.” (es), understood launch:? (wanted launch:ci)
- es-ar-daniela/es-launch-csv-2: said “Lanzá la segunda.”, heard “La segunda.” (es), understood none (wanted launch:csv)
- es-ar-daniela/es-mute-1: said “Silencio.”, heard “See you in show.” (en), understood none (wanted mute)
- es-ar-daniela/es-mute-3: said “Callate un rato.”, heard “Que hacía terapia.” (es), understood none (wanted mute)
- es-ar-daniela/es-next-1: said “Siguiente sprint.”, heard “Siente sprint.” (es), understood none (wanted next)
- es-ar-daniela/es-pause-1: said “Pausá.”, heard “Go saw.” (en), understood none (wanted pause)
- es-ar-daniela/es-recenter-2: said “Vení acá.”, heard “Then you're good.” (en), understood none (wanted recenter)
- es-ar-daniela/es-reject-1: said “Devolvela.”, heard “De Orbella.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-3: said “No, rechazala.”, heard “No os pechas a la.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-5: said “Devuélvela al desarrollador.”, heard “Te huele al desarrollador.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-7: said “Rechazada.”, heard “Hechazada.” (es), understood none (wanted reject)
- es-ar-daniela/es-restart-1: said “Reiniciá.”, heard “Iniciá.” (es), understood launch:? (wanted restart)
- es-ar-daniela/es-resume-1: said “Seguí.”, heard “Say.” (en), understood none (wanted resume)
- es-ar-daniela/es-resume-3: said “Reanudá el sprint.”, heard “Tenlo al sprint.” (es), understood none (wanted resume)
- es-ar-daniela/es-yes-1: said “Sí.”, heard “See ya.” (en), understood none (wanted yes)
- es-dora/es-approve-3: said “Dale, aprobá la entrega.”, heard “Darling.” (en), understood none (wanted approve)
- es-dora/es-help-2: said “Ayuda.”, heard “I do that.” (en), understood none (wanted help)
- es-dora/es-launch-ci-1: said “Lanzá la del CI.”, heard “Lansala.” (en), understood none (wanted launch:ci)
- es-dora/es-pause-1: said “Pausá.”, heard “Both sides.” (en), understood none (wanted pause)
- es-dora/es-recenter-2: said “Vení acá.”, heard “Beniyaka.” (en), understood none (wanted recenter)
- es-dora/es-reject-3: said “No, rechazala.”, heard “No.” (es), understood no (wanted reject)
- es-dora/es-reject-5: said “Devuélvela al desarrollador.”, heard “Te vuélvela al desarrollador.” (es), understood none (wanted reject)
- es-dora/es-reject-7: said “Rechazada.”, heard “Prechaçada.” (en), understood none (wanted reject)
- es-dora/es-resume-1: said “Seguí.”, heard “So gay.” (en), understood none (wanted resume)
- es-dora/es-status-1: said “¿Cómo va?”, heard “Come on.” (en), understood none (wanted status)
- es-dora/es-yes-1: said “Sí.”, heard “Say it.” (en), understood none (wanted yes)
- es-dora/es-yes-2: said “Sí, dale.”, heard “See you.” (en), understood none (wanted yes)
- es-es-davefx/es-approve-1: said “Aprobá.”, heard “Prr.” (en), understood none (wanted approve)
- es-es-davefx/es-approve-2: said “Aprobala.”, heard “Arrubada.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-3: said “Dale, aprobá la entrega.”, heard “Dale. Aprova la entrega.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-4: said “Está bien, apruebo.”, heard “Está bien. A prueba.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-5: said “Apruebe la entrega, por favor.”, heard “No probé la entera. Por favor.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-7: said “Eh, sí, aprobado.”, heard “Sí. Está probado.” (es), understood none (wanted approve)
- es-es-davefx/es-launch-ci-1: said “Lanzá la del CI.”, heard “Lanzá la del fe.” (es), understood launch:? (wanted launch:ci)
- es-es-davefx/es-launch-ci-2: said “Arrancá la tercera tarea.”, heard “Adelante.” (es), understood yes (wanted launch:ci)
- es-es-davefx/es-launch-ci-3: said “Empezá la del runner.”, heard “Empezá la del bomber.” (es), understood launch:? (wanted launch:ci)
- es-es-davefx/es-pause-1: said “Pausá.”, heard “That's it.” (en), understood none (wanted pause)
- es-es-davefx/es-pause-4: said “Poné pausa, por favor.”, heard “Poné posa por favor.” (es), understood none (wanted pause)
- es-es-davefx/es-recenter-2: said “Vení acá.”, heard “Vení en acá.” (es), understood none (wanted recenter)
- es-es-davefx/es-reject-3: said “No, rechazala.”, heard “No.” (es), understood no (wanted reject)
- es-es-davefx/es-reject-7: said “Rechazada.”, heard “Deja sada.” (es), understood none (wanted reject)
- es-es-davefx/es-restart-1: said “Reiniciá.”, heard “Enicia.” (es), understood none (wanted restart)
- es-es-davefx/es-resume-1: said “Seguí.”, heard “Say it.” (en), understood none (wanted resume)
- es-es-davefx/es-yes-1: said “Sí.”, heard “See.” (en), understood none (wanted yes)
- es-es-davefx/es-yes-2: said “Sí, dale.”, heard “See you.” (en), understood none (wanted yes)
- es-mx-claude/es-approve-1: said “Aprobá.”, heard “Aprova.” (es), understood none (wanted approve)
- es-mx-claude/es-approve-4: said “Está bien, apruebo.”, heard “Está bien. A prueba.” (es), understood none (wanted approve)
- es-mx-claude/es-next-1: said “Siguiente sprint.”, heard “Siguiente splinter.” (es), understood none (wanted next)
- es-mx-claude/es-pause-1: said “Pausá.”, heard “Go ahead.” (en), understood yes (wanted pause)
- es-mx-claude/es-reject-3: said “No, rechazala.”, heard “No. Decha sala.” (es), understood none (wanted reject)
- es-mx-claude/es-reject-7: said “Rechazada.”, heard “Dechazada.” (es), understood none (wanted reject)
- es-mx-claude/es-resume-1: said “Seguí.”, heard “Serif.” (en), understood none (wanted resume)
- es-mx-claude/es-unmute-2: said “Con sonido.”, heard “Con sonidos.” (es), understood none (wanted unmute)
- es-mx-claude/es-yes-1: said “Sí.”, heard “C.” (en), understood none (wanted yes)

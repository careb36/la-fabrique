## fw-small-prompt

| language | phrases | commands right | WER | language right | s/phrase |
|---|---|---|---|---|---|
| en | 186 | 95% | 5.9% | 100% | 2.60 |
| es | 248 | 77% | 24.9% | 85% | 2.63 |
| all | 434 | 84% | 16.7% | 91% | 2.62 |

| voice | commands right | WER |
|---|---|---|
| en-heart | 98% | 2.3% |
| en-us-lessac | 97% | 2.2% |
| en-us-ryan | 89% | 13.3% |
| es-ar-daniela | 65% | 36.9% |
| es-dora | 84% | 23.4% |
| es-es-davefx | 74% | 23.7% |
| es-mx-claude | 84% | 15.5% |

| intent | es | en |
|---|---|---|
| approve | 50% | 86% |
| help | 67% | 89% |
| launch:ci | 75% | 89% |
| launch:csv | 100% | 100% |
| launch:reset | 100% | 100% |
| mute | 92% | 89% |
| next | 88% | 100% |
| no | 92% | 100% |
| none | 100% | 100% |
| pause | 75% | 92% |
| recenter | 75% | 89% |
| reject | 64% | 100% |
| restart | 75% | 100% |
| resume | 69% | 100% |
| status | 88% | 100% |
| unmute | 88% | 100% |
| yes | 63% | 83% |

Misses: 68

- en-heart/en-recenter-1: said “Recenter the panels.”, heard “Resenter the panels.” (en), understood none (wanted recenter)
- en-us-lessac/en-approve-4: said “Ship it.”, heard “Chip it.” (en), understood none (wanted approve)
- en-us-lessac/en-launch-ci-1: said “Launch the CI one.”, heard “Launch the CDI one.” (en), understood launch:? (wanted launch:ci)
- en-us-ryan/en-approve-1: said “Approve.”, heard “Unbrew.” (en), understood none (wanted approve)
- en-us-ryan/en-approve-4: said “Ship it.”, heard “Shut that.” (en), understood none (wanted approve)
- en-us-ryan/en-help-2: said “Help.”, heard “Oh.” (en), understood none (wanted help)
- en-us-ryan/en-mute-1: said “Mute.”, heard “Close.” (en), understood none (wanted mute)
- en-us-ryan/en-pause-1: said “Pause.”, heard “How is it.” (en), understood none (wanted pause)
- en-us-ryan/en-yes-1: said “Yes.”, heard “Next.” (en), understood next (wanted yes)
- en-us-ryan/en-yes-3: said “Confirmed.”, heard “Timvern.” (en), understood none (wanted yes)
- es-ar-daniela/es-approve-1: said “Aprobá.”, heard “Paproba.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-2: said “Aprobala.”, heard “Aprovala.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-3: said “Dale, aprobá la entrega.”, heard “Dale. Tapó la entrega.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-4: said “Está bien, apruebo.”, heard “Está bien. La pruebo.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-5: said “Apruebe la entrega, por favor.”, heard “Aprovele la entidad por favor.” (es), understood none (wanted approve)
- es-ar-daniela/es-help-1: said “¿Qué puedo decir?”, heard “Te puedo vacir.” (es), understood none (wanted help)
- es-ar-daniela/es-help-2: said “Ayuda.”, heard “Adela.” (es), understood none (wanted help)
- es-ar-daniela/es-launch-ci-3: said “Empezá la del runner.”, heard “Empezá la del runar.” (es), understood launch:? (wanted launch:ci)
- es-ar-daniela/es-mute-1: said “Silencio.”, heard “See you in show.” (en), understood none (wanted mute)
- es-ar-daniela/es-pause-1: said “Pausá.”, heard “Go son.” (en), understood none (wanted pause)
- es-ar-daniela/es-recenter-2: said “Vení acá.”, heard “Diniaka.” (en), understood none (wanted recenter)
- es-ar-daniela/es-recenter-3: said “Traé todo al frente.”, heard “De todo el frente.” (es), understood none (wanted recenter)
- es-ar-daniela/es-reject-1: said “Devolvela.”, heard “Te volvela.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-2: said “Mandala de vuelta.”, heard “Venda la devuelta.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-3: said “No, rechazala.”, heard “No os pechas a la.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-5: said “Devuélvela al desarrollador.”, heard “Te huele al desarrollador.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-7: said “Rechazada.”, heard “Hechazada.” (es), understood none (wanted reject)
- es-ar-daniela/es-restart-1: said “Reiniciá.”, heard “Start.” (en), understood launch:? (wanted restart)
- es-ar-daniela/es-resume-1: said “Seguí.”, heard “Say.” (en), understood none (wanted resume)
- es-ar-daniela/es-resume-3: said “Reanudá el sprint.”, heard “Tenlo al sprint.” (es), understood none (wanted resume)
- es-ar-daniela/es-status-1: said “¿Cómo va?”, heard “Como es.” (es), understood none (wanted status)
- es-ar-daniela/es-yes-1: said “Sí.”, heard “See ya.” (en), understood none (wanted yes)
- es-dora/es-approve-3: said “Dale, aprobá la entrega.”, heard “Dali aprovala entrega.” (en), understood none (wanted approve)
- es-dora/es-help-2: said “Ayuda.”, heard “I knew that.” (en), understood none (wanted help)
- es-dora/es-launch-ci-1: said “Lanzá la del CI.”, heard “Let's start with the say.” (en), understood launch:? (wanted launch:ci)
- es-dora/es-recenter-2: said “Vení acá.”, heard “Beniyakar.” (en), understood none (wanted recenter)
- es-dora/es-reject-5: said “Devuélvela al desarrollador.”, heard “Te vuélvela al desarrollador.” (es), understood none (wanted reject)
- es-dora/es-reject-7: said “Rechazada.”, heard “Pre-chassada.” (en), understood none (wanted reject)
- es-dora/es-resume-1: said “Seguí.”, heard “Sagaip.” (en), understood none (wanted resume)
- es-dora/es-status-1: said “¿Cómo va?”, heard “Come on, bud.” (en), understood none (wanted status)
- es-dora/es-yes-1: said “Sí.”, heard “Say it.” (en), understood none (wanted yes)
- es-dora/es-yes-2: said “Sí, dale.”, heard “See you later.” (en), understood none (wanted yes)
- es-es-davefx/es-approve-1: said “Aprobá.”, heard “Correct.” (en), understood yes (wanted approve)
- es-es-davefx/es-approve-2: said “Aprobala.”, heard “Revala.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-3: said “Dale, aprobá la entrega.”, heard “Dale a probar la entrega.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-4: said “Está bien, apruebo.”, heard “Está bien. Adpruebo.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-5: said “Apruebe la entrega, por favor.”, heard “No probar de la entretas. Por favor.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-7: said “Eh, sí, aprobado.”, heard “Eh si, te ha probado.” (es), understood none (wanted approve)
- es-es-davefx/es-launch-ci-1: said “Lanzá la del CI.”, heard “Lanzá la del CEI.” (es), understood launch:? (wanted launch:ci)
- es-es-davefx/es-no-1: said “No.”, heard “Nope.” (en), understood none (wanted no)
- es-es-davefx/es-pause-1: said “Pausá.”, heard “That's it.” (en), understood none (wanted pause)
- es-es-davefx/es-pause-4: said “Poné pausa, por favor.”, heard “Poné posa por favor.” (es), understood none (wanted pause)
- es-es-davefx/es-reject-3: said “No, rechazala.”, heard “No. Pero te ha salido.” (es), understood none (wanted reject)
- es-es-davefx/es-reject-7: said “Rechazada.”, heard “Dejasada.” (es), understood none (wanted reject)
- es-es-davefx/es-restart-1: said “Reiniciá.”, heard “Venícia.” (es), understood none (wanted restart)
- es-es-davefx/es-resume-1: said “Seguí.”, heard “Ok.” (en), understood yes (wanted resume)
- es-es-davefx/es-yes-1: said “Sí.”, heard “See.” (en), understood none (wanted yes)
- es-es-davefx/es-yes-2: said “Sí, dale.”, heard “See you.” (en), understood none (wanted yes)
- es-mx-claude/es-approve-1: said “Aprobá.”, heard “Aprova.” (es), understood none (wanted approve)
- es-mx-claude/es-approve-3: said “Dale, aprobá la entrega.”, heard “Dale. Aprova la entrega.” (es), understood none (wanted approve)
- es-mx-claude/es-help-2: said “Ayuda.”, heard “Any other.” (en), understood none (wanted help)
- es-mx-claude/es-next-1: said “Siguiente sprint.”, heard “Siguiente splinter.” (es), understood none (wanted next)
- es-mx-claude/es-pause-1: said “Pausá.”, heard “Bossa.” (en), understood none (wanted pause)
- es-mx-claude/es-reject-3: said “No, rechazala.”, heard “No decha sala.” (es), understood none (wanted reject)
- es-mx-claude/es-restart-1: said “Reiniciá.”, heard “Re-initia.” (en), understood none (wanted restart)
- es-mx-claude/es-resume-1: said “Seguí.”, heard “Serif.” (en), understood none (wanted resume)
- es-mx-claude/es-unmute-2: said “Con sonido.”, heard “Con sonidos.” (es), understood none (wanted unmute)
- es-mx-claude/es-yes-1: said “Sí.”, heard “Csv.” (en), understood none (wanted yes)

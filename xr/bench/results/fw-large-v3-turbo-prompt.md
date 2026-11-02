## fw-large-v3-turbo-prompt

| language | phrases | commands right | WER | language right | s/phrase |
|---|---|---|---|---|---|
| en | 186 | 91% | 27.5% | 100% | 13.28 |
| es | 248 | 81% | 23.2% | 94% | 9.70 |
| all | 434 | 85% | 25.0% | 97% | 11.24 |

| voice | commands right | WER |
|---|---|---|
| en-heart | 97% | 31.3% |
| en-us-lessac | 95% | 25.2% |
| en-us-ryan | 82% | 26.0% |
| es-ar-daniela | 63% | 36.8% |
| es-dora | 87% | 27.2% |
| es-es-davefx | 82% | 18.8% |
| es-mx-claude | 90% | 9.9% |

| intent | es | en |
|---|---|---|
| approve | 61% | 90% |
| help | 83% | 89% |
| launch:ci | 67% | 67% |
| launch:csv | 83% | 78% |
| launch:reset | 92% | 100% |
| mute | 92% | 89% |
| next | 88% | 100% |
| no | 75% | 78% |
| none | 100% | 100% |
| pause | 81% | 92% |
| recenter | 83% | 100% |
| reject | 82% | 100% |
| restart | 83% | 100% |
| resume | 69% | 92% |
| status | 94% | 100% |
| unmute | 88% | 83% |
| yes | 75% | 83% |

Misses: 64

- en-heart/en-launch-ci-1: said “Launch the CI one.”, heard “Launch the CI1.” (en), understood launch:? (wanted launch:ci)
- en-heart/en-no-1: said “No.”, heard “No. No.” (en), understood none (wanted no)
- en-us-lessac/en-launch-ci-1: said “Launch the CI one.”, heard “Launch. Launch. The seed. I won.” (en), understood launch:? (wanted launch:ci)
- en-us-lessac/en-launch-csv-2: said “Launch the second one.”, heard “Lunch. Lunch. The second one.” (en), understood none (wanted launch:csv)
- en-us-lessac/en-unmute-1: said “Unmute.”, heard “A mute.” (en), understood mute (wanted unmute)
- en-us-ryan/en-approve-1: said “Approve.”, heard “Let's go.” (en), understood none (wanted approve)
- en-us-ryan/en-approve-4: said “Ship it.”, heard “Shut it. Shut it.” (en), understood none (wanted approve)
- en-us-ryan/en-help-2: said “Help.”, heard “Oh.” (en), understood none (wanted help)
- en-us-ryan/en-launch-ci-1: said “Launch the CI one.”, heard “Lunch. The CI won.” (en), understood none (wanted launch:ci)
- en-us-ryan/en-launch-csv-1: said “Launch the CSV export.”, heard “Lunch. This is easy. As we export.” (en), understood none (wanted launch:csv)
- en-us-ryan/en-mute-1: said “Mute.”, heard “What. What.” (en), understood none (wanted mute)
- en-us-ryan/en-no-1: said “No.”, heard “Well.” (en), understood none (wanted no)
- en-us-ryan/en-pause-1: said “Pause.”, heard “Bye. Bye.” (en), understood none (wanted pause)
- en-us-ryan/en-resume-1: said “Resume.”, heard “What's happening. What's happening. What's happening.” (en), understood status (wanted resume)
- en-us-ryan/en-yes-1: said “Yes.”, heard “Masks.” (en), understood none (wanted yes)
- en-us-ryan/en-yes-3: said “Confirmed.”, heard “Tim Verne.” (en), understood none (wanted yes)
- es-ar-daniela/es-approve-1: said “Aprobá.”, heard “La prueba.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-2: said “Aprobala.”, heard “Aprubala.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-3: said “Dale, aprobá la entrega.”, heard “Dale. Tapeo a la entrega.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-4: said “Está bien, apruebo.”, heard “Está bien. La pruebo.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-5: said “Apruebe la entrega, por favor.”, heard “Apleo de la entrada. Por favor.” (es), understood none (wanted approve)
- es-ar-daniela/es-approve-7: said “Eh, sí, aprobado.”, heard “Let's go ahead.” (en), understood yes (wanted approve)
- es-ar-daniela/es-help-1: said “¿Qué puedo decir?”, heard “Te puedo decir.” (es), understood none (wanted help)
- es-ar-daniela/es-help-2: said “Ayuda.”, heard “Arroba.” (es), understood none (wanted help)
- es-ar-daniela/es-launch-ci-1: said “Lanzá la del CI.”, heard “Lanzá la DCI.” (es), understood launch:? (wanted launch:ci)
- es-ar-daniela/es-launch-ci-3: said “Empezá la del runner.”, heard “Empezá la del runar.” (es), understood launch:? (wanted launch:ci)
- es-ar-daniela/es-launch-csv-2: said “Lanzá la segunda.”, heard “La ensalada segunda.” (es), understood none (wanted launch:csv)
- es-ar-daniela/es-launch-csv-3: said “Dale con el CSV.”, heard “Dale con SSB.” (es), understood launch:? (wanted launch:csv)
- es-ar-daniela/es-launch-reset-3: said “Empezá con la de la contraseña.”, heard “Empezá con la de la contrasera.” (es), understood launch:? (wanted launch:reset)
- es-ar-daniela/es-pause-1: said “Pausá.”, heard “What's happening. What's happening.” (en), understood status (wanted pause)
- es-ar-daniela/es-recenter-3: said “Traé todo al frente.”, heard “Te todo el frente.” (es), understood none (wanted recenter)
- es-ar-daniela/es-reject-1: said “Devolvela.”, heard “Teo Lvela.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-3: said “No, rechazala.”, heard “No. No. Especha sola.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-5: said “Devuélvela al desarrollador.”, heard “Te huele al desarrollador.” (es), understood none (wanted reject)
- es-ar-daniela/es-reject-7: said “Rechazada.”, heard “Hecha asada.” (es), understood none (wanted reject)
- es-ar-daniela/es-restart-1: said “Reiniciá.”, heard “Inicia.” (es), understood launch:? (wanted restart)
- es-ar-daniela/es-resume-1: said “Seguí.”, heard “Si.” (es), understood yes (wanted resume)
- es-ar-daniela/es-resume-3: said “Reanudá el sprint.”, heard “Tenlo al sprint.” (es), understood none (wanted resume)
- es-ar-daniela/es-yes-1: said “Sí.”, heard “Csie.” (es), understood none (wanted yes)
- es-dora/es-approve-2: said “Aprobala.”, heard “Aprovala.” (es), understood none (wanted approve)
- es-dora/es-launch-ci-1: said “Lanzá la del CI.”, heard “Lanzá. Lanzá. La del 6.” (es), understood launch:? (wanted launch:ci)
- es-dora/es-no-1: said “No.”, heard “No. No.” (en), understood none (wanted no)
- es-dora/es-reject-7: said “Rechazada.”, heard “Prichasada.” (es), understood none (wanted reject)
- es-dora/es-resume-1: said “Seguí.”, heard “So. Okay.” (en), understood none (wanted resume)
- es-dora/es-status-1: said “¿Cómo va?”, heard “Come on. Bye.” (en), understood none (wanted status)
- es-dora/es-yes-1: said “Sí.”, heard “Let's see.” (en), understood none (wanted yes)
- es-dora/es-yes-2: said “Sí, dale.”, heard “See. See. Dale.” (en), understood none (wanted yes)
- es-es-davefx/es-approve-1: said “Aprobá.”, heard “Ta-ra.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-2: said “Aprobala.”, heard “Arrobala.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-5: said “Apruebe la entrega, por favor.”, heard “No pruebe la entreta. Por favor.” (es), understood none (wanted approve)
- es-es-davefx/es-approve-7: said “Eh, sí, aprobado.”, heard “Te si. Te ha probado.” (es), understood none (wanted approve)
- es-es-davefx/es-launch-ci-3: said “Empezá la del runner.”, heard “Empezala. Adelumear.” (es), understood launch:? (wanted launch:ci)
- es-es-davefx/es-mute-2: said “Sacá el sonido.”, heard “Se cae el sonido.” (es), understood none (wanted mute)
- es-es-davefx/es-no-1: said “No.”, heard “No. No.” (es), understood none (wanted no)
- es-es-davefx/es-pause-1: said “Pausá.”, heard “Okay. Okay.” (en), understood none (wanted pause)
- es-es-davefx/es-recenter-1: said “Centrá los paneles.”, heard “Entra los paneles.” (es), understood none (wanted recenter)
- es-es-davefx/es-restart-1: said “Reiniciá.”, heard “Pe inicia.” (es), understood launch:? (wanted restart)
- es-es-davefx/es-resume-1: said “Seguí.”, heard “Take it.” (en), understood none (wanted resume)
- es-mx-claude/es-next-1: said “Siguiente sprint.”, heard “Siguiente splinter.” (es), understood none (wanted next)
- es-mx-claude/es-no-1: said “No.”, heard “Nos.” (es), understood none (wanted no)
- es-mx-claude/es-pause-1: said “Pausá.”, heard “Bosa.” (es), understood none (wanted pause)
- es-mx-claude/es-resume-1: said “Seguí.”, heard “Serig.” (es), understood none (wanted resume)
- es-mx-claude/es-unmute-2: said “Con sonido.”, heard “Con sonidos.” (es), understood none (wanted unmute)
- es-mx-claude/es-yes-1: said “Sí.”, heard “Si. Si.” (es), understood none (wanted yes)

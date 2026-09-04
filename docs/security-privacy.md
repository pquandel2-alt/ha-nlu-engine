# Sicherheits- und Datenschutzmodell

HomeIntent arbeitet lokal und besitzt keine generative Laufzeitabhängigkeit.
Parser, Hausgraph, Gedächtnis, Reasoner, Statistik, Persona und Adapter haben
keinen HA-Servicezugriff. Nur ein validierter `ServiceCallPlan` darf die
Execution Policy und danach `async_execute_service_plan` erreichen.

Vor jeder verzögerten oder gespeicherten Aktion werden Ziel-Snapshot,
Verfügbarkeit, gemeldete Capability und Policy erneut geprüft. Queries,
Ambiguität, unsichere Sprache, Gedächtnisfakten und Statistik erzeugen keinen
Plan. AUTO ist nur für explizit konfigurierte IDs, reversible Operationen und
LOW-Risk erlaubt; bei fehlender Freigabe wird es ASK. Kritische Aktionen sind
kein lernbares AUTO.

Eine nach erfolgreicher Ausführung registrierte Wirkungserwartung besitzt
keine Ausführungsberechtigung. Ihr Ablauf darf nur informieren; es gibt weder
Retry noch Folgeplan. Frigate-Daten bleiben statistische Evidenz, enthalten
keine Rohbilder und können weder Faktenstatus noch Policy-Allowlist erhöhen.
Die Adapterpuffer sind RAM-begrenzt und werden nach Neustart nicht wiederbelebt.

Das Gedächtnis ist opt-in, lokal, migrationsfähig, ablaufbar und löschbar.
Persönliche dauerhafte Einträge benötigen Bestätigung und Benutzerbindung.
Beim kontrollierten Löschen werden Inhalt und Personenzuordnung im Tombstone
überschrieben; SQLite `secure_delete` ist aktiv und das WAL wird anschließend
trunkiert. Nur ID, Typ und Zeitmetadaten bleiben zur Löschdiagnose erhalten.
Diagnosen und redigierte Exporte enthalten keine Entity-IDs, Personen-IDs,
Zustände, Transkripte oder Erinnerungsinhalte. Sie zeigen ausschließlich
Schema-, Herkunfts- und Typzähler sowie die Anzahl statistischer Serien und
Beobachtungen, damit erlernte Daten sichtbar bleiben, ohne private Inhalte zu
exportieren.

const labels: Record<string, string> = {
  "Connect your Claude subscription before sending a message.":
    "Lidhni abonimin Claude para se të dërgoni mesazh.",
  "Claude connection failed. Check your subscription connection and try again.":
    "Lidhja me Claude dështoi. Kontrolloni lidhjen e abonimit dhe provoni përsëri.",
  "Claude could not complete this response. Check your subscription limits and retry.":
    "Claude nuk përfundoi përgjigjen. Kontrolloni kufijtë e abonimit dhe provoni përsëri.",
  "Claude models could not be loaded. Check your subscription connection.":
    "Modelet Claude nuk u ngarkuan. Kontrolloni lidhjen e abonimit.",
  "This Claude login has expired. Start a new connection.":
    "Hyrja në Claude ka skaduar. Nisni një lidhje të re.",
  "The selected model could not finish the report narrative. Check your subscription and retry.":
    "Modeli i zgjedhur nuk përfundoi tekstin e raportit. Kontrolloni abonimin dhe provoni përsëri.",
  gathering: "Duke mbledhur të dhënat",
  analyzing: "Duke analizuar të dhënat",
  excel: "Duke krijuar Excel-in dhe grafikët",
  validating: "Duke kontrolluar Excel-in dhe të dhënat",
  repairing: "Duke korrigjuar skriptin e raportit",
  connected: "I lidhur",
  disconnected: "I shkëputur",
  not_connected: "I palidhur",
  not_configured: "Pa konfigurim",
  not_checked: "Pa kontrolluar",
  error: "Gabim",
  queued: "Në pritje",
  running: "Duke u përgatitur",
  completed: "Përfunduar",
  failed: "Dështoi",
  blocked: "Në pritje të të dhënave",
  interrupted: "U ndërpre",
  streaming: "Duke shkruar",
  active: "Aktiv",
  disabled: "Joaktiv",
  admin: "Administrator",
  member: "Anëtar",
  devs: "Devs",
  president: "President",
  manager: "Manager",
  "Executive overview": "Përmbledhje për drejtuesit",
  "Sales performance": "Performanca e shitjeve",
  "Operations brief": "Përmbledhje e operacioneve",
  "Connection check": "Kontrolli i lidhjes",
  "Database table and column catalog": "Katalogu i tabelave dhe kolonave",
};
export const label = (value: string) => labels[value] || value;
const errors: Record<string, string> = {
  "The response reached the server time limit before it finished. Check slow database tools in Administration → Traffic, then retry.":
    "Përgjigjja arriti kufirin kohor të serverit pa përfunduar. Kontrolloni vonesat e mjeteve të databazës te Administrimi → Trafiku dhe provoni përsëri.",
  "SAP HANA certificate hostname mismatch. Use the DNS name on the certificate or configure HANA_TLS_SERVER_NAME to the verified server identity.":
    "Emri i hostit nuk përputhet me certifikatën SAP HANA. Përdorni emrin DNS në certifikatë ose konfiguroni HANA_TLS_SERVER_NAME me identitetin e verifikuar të serverit.",
  "The SAP HANA server certificate has expired. Ask the server administrator to renew it.":
    "Certifikata e serverit SAP HANA ka skaduar. Kërkoni rinovimin nga administratori i serverit.",
  "SAP HANA certificate verification failed. Configure HANA_TLS_CA_CERTIFICATE with the trusted root/intermediate CA chain and check the certificate hostname and validity.":
    "Verifikimi i certifikatës SAP HANA dështoi. Vendosni zinxhirin CA të besuar në HANA_TLS_CA_CERTIFICATE dhe kontrolloni emrin e hostit dhe vlefshmërinë e certifikatës.",
  "The SAP HANA CA bundle is invalid or unavailable. Check HANA_TLS_CA_CERTIFICATE and backend storage permissions.":
    "Zinxhiri CA i SAP HANA është i pavlefshëm ose mungon. Kontrolloni HANA_TLS_CA_CERTIFICATE dhe lejet e ruajtjes në backend.",
  "Provide trusted CA certificates in PEM format, without private keys.":
    "Vendosni certifikata CA të besuara në format PEM, pa çelësa privatë.",
  "Use the DNS server name from the HANA certificate, without a scheme, port or path.":
    "Përdorni emrin DNS të serverit nga certifikata HANA, pa protokoll, portë ose shteg.",

  "The SAP HANA .env configuration could not be read. Check field values and backend file permissions.":
    "Konfigurimi SAP HANA në .env nuk u lexua. Kontrolloni vlerat dhe lejet e backend-it.",
  "Set the correct SQL port when changing database type.":
    "Vendosni portën SQL të saktë kur ndryshoni llojin e databazës.",
  "SAP HANA authentication failed. Check HANA_USER, HANA_PASSWORD and the tenant SQL port.":
    "Autentikimi SAP HANA dështoi. Kontrolloni HANA_USER, HANA_PASSWORD dhe portën SQL të tenant-it.",
  "SAP HANA denied access. Check SELECT and catalog metadata permissions for the reporting user.":
    "SAP HANA refuzoi qasjen. Kontrolloni lejet SELECT dhe të katalogut për përdoruesin e raporteve.",
  "The SAP HANA table, view or column is unavailable. Refresh the schema and check object permissions.":
    "Tabela, pamja ose kolona SAP HANA nuk është e disponueshme. Rifreskoni skemën dhe kontrolloni lejet.",
  "SAP HANA TLS validation failed. Check the encryption setting and the server certificate trust chain.":
    "Kontrolli TLS i SAP HANA dështoi. Kontrolloni enkriptimin dhe zinxhirin e certifikatës së serverit.",
  "SAP HANA timed out. Check the host, SQL port, network and query performance.":
    "SAP HANA tejkaloi kohën e pritjes. Kontrolloni hostin, portën SQL, rrjetin dhe performancën e pyetjes.",
  "SAP HANA could not establish a connection. Check HANA_HOST and the HANA SQL port; SQL Server ports and protocols are incompatible.":
    "Lidhja SAP HANA dështoi. Kontrolloni HANA_HOST dhe portën SQL të HANA; portat dhe protokollet SQL Server nuk përputhen.",
  "SAP HANA could not complete the request. Check the tenant, SQL port, permissions and query.":
    "SAP HANA nuk e përfundoi kërkesën. Kontrolloni tenant-in, portën SQL, lejet dhe pyetjen.",
  "The SAP HANA SQL endpoint did not select the requested tenant. Use the correct tenant SQL port or SYSTEMDB routing endpoint.":
    "Porta SQL e SAP HANA nuk zgjodhi tenant-in e kërkuar. Përdorni portën SQL të saktë ose pikën e rutimit SYSTEMDB.",
  "The project .env could not be updated. Check its writable mount and backend file permissions.":
    "Skedari .env i projektit nuk u ruajt. Kontrolloni montimin me shkrim dhe lejet e backend-it.",
  "The saved connection .env could not be read. Check backend file permissions.":
    "Konfigurimi i lidhjes në .env nuk u lexua. Kontrolloni lejet e backend-it.",
  "The saved connection profile is missing from the project .env. Restore its configuration.":
    "Profili i lidhjes mungon në .env të projektit. Riktheni konfigurimin e tij.",
  "The project .env recovery could not complete. Check backend file permissions and storage.":
    "Rikthimi i .env nuk përfundoi. Kontrolloni lejet e backend-it dhe hapësirën e ruajtjes.",
  "HANA_PORT must be a number between 1 and 65535.":
    "HANA_PORT duhet të jetë një numër nga 1 deri në 65535.",
  "HANA TLS options must be true or false.":
    "Opsionet TLS të HANA duhet të jenë true ose false.",
  "SAP HANA driver is unavailable. Rebuild the application with hdbcli installed.":
    "Drejtuesi SAP HANA mungon. Rindërtoni aplikacionin me hdbcli të instaluar.",

  "Select a database from discover_databases before reading business data.":
    "Zbuloni databazat e lidhjes dhe zgjidhni njërën për analizë.",
  "This connection is disconnected or has been removed. Ask an administrator to reconnect it.":
    "Lidhja është shkëputur ose hequr. Kërkoni rilidhjen nga administratori.",
  "Workbook script could not pass execution and validation after three attempts. No downloadable report was published.":
    "Skripti i Excel-it nuk kaloi ekzekutimin dhe kontrollin pas tri përpjekjeve. Nuk u publikua raport i shkarkueshëm.",
  "Workbook script isolation is unavailable. Check Linux Landlock and seccomp support.":
    "Izolimi i skriptit të Excel-it nuk është i disponueshëm. Kontrolloni mbështetjen Linux për Landlock dhe seccomp.",
  "Workbook script exceeded its execution time limit.":
    "Skripti i Excel-it tejkaloi kohën e lejuar të ekzekutimit.",
  "The complete result exceeds the configured row limit. Ask an administrator to increase it; no partial report was generated.":
    "Rezultati i plotë tejkalon kufirin e rreshtave. Kërkoni nga administratori ta rrisë kufirin; nuk u krijua raport i pjesshëm.",
  "The complete result exceeds the configured size limit. Ask an administrator to increase it; no partial report was generated.":
    "Rezultati i plotë tejkalon kufirin e madhësisë. Kërkoni nga administratori ta rrisë kufirin; nuk u krijua raport i pjesshëm.",
  "The complete report exceeds the configured export limits. Ask an administrator to increase them; no partial report was generated.":
    "Raporti i plotë tejkalon kufijtë e eksportimit. Kërkoni nga administratori t'i rrisë kufijtë; nuk u krijua raport i pjesshëm.",
  "A requested breakdown is incomplete. No partial report was generated.":
    "Një ndarje e kërkuar është e paplotë. Nuk u krijua raport i pjesshëm.",
  "The server has reached its simultaneous conversation capacity. Stop a response or try again shortly.":
    "Serveri ka arritur kufirin e bisedave njëkohësisht. Ndërprisni një përgjigje ose provoni përsëri pak më vonë.",
  "The uploaded document is too large after decompression.":
    "Skedari është tepër i madh pas hapjes së përmbajtjes së kompresuar.",
  "Uploaded tables support at most 10000 rows and 100 columns.":
    "Tabelat e ngarkuara mbështesin deri në 10 000 rreshta dhe 100 kolona.",
  "Upload at most 20 worksheets per file.":
    "Ngarkoni deri në 20 fletë pune për skedar.",
  "The uploaded worksheet exceeds the row or column limit.":
    "Fleta e punës tejkalon kufirin e rreshtave ose kolonave.",
  "The upload exceeds the cell limit.": "Skedari tejkalon kufirin e qelizave.",
  "An uploaded cell exceeds the text limit.":
    "Teksti në një qelizë tejkalon kufirin e lejuar.",
  "PDF uploads support at most 100 pages.":
    "PDF-ja mund të ketë deri në 100 faqe.",
  "A PDF page exceeds the extraction limit.":
    "Një faqe e PDF-së tejkalon kufirin e leximit.",
  "The uploaded document exceeds the text extraction limit.":
    "Dokumenti tejkalon kufirin e tekstit që mund të lexohet.",
  "The extracted upload exceeds the data limit.":
    "Të dhënat e nxjerra nga skedari tejkalojnë kufirin e lejuar.",
  "Upload Excel (.xlsx), CSV, PDF, Word (.docx), or text files.":
    "Ngarkoni Excel (.xlsx), CSV, PDF me tekst, Word (.docx) ose skedar tekst.",
  "Uploads must be smaller than 12 MB.":
    "Skedarët duhet të jenë më të vegjël se 12 MB.",
  "The uploaded file is empty.": "Skedari i ngarkuar është bosh.",
  "The uploaded file could not be read. Check its format and contents.":
    "Skedari nuk u lexua. Kontrolloni formatin dhe përmbajtjen.",
  "The upload exceeded parsing limits or could not be read.":
    "Skedari tejkaloi kufijtë e leximit ose nuk mund të lexohej.",
  "Your private upload storage limit has been reached.":
    "Është arritur kufiri i hapësirës private për skedarët tuaj.",
  "This conversation has reached its upload limit. Start a new conversation.":
    "Është arritur kufiri i skedarëve në këtë bisedë. Hapni një bisedë të re.",
  "Encrypted uploads are not supported.":
    "Skedarët e mbrojtur me fjalëkalim nuk lexohen. Ngarkoni një kopje të pambrojtur.",
  "This PDF has no readable text. Upload a text-based PDF or Excel file.":
    "PDF-ja nuk përmban tekst të lexueshëm. Ngarkoni PDF me tekst ose Excel.",
  "Attachment not found.": "Skedari i bashkëngjitur nuk u gjet.",
  "Use an Excel file with a formatted table as the format reference.":
    "Përdorni një skedar Excel me tabelë të formatuar si model paraqitjeje.",
  "Workbook translations are missing. Retry report generation.":
    "Mungojnë përkthimet e Excel-it. Provoni përsëri krijimin e raportit.",
  "Workbook translations are incomplete. Retry report generation.":
    "Përkthimet e Excel-it nuk janë të plota. Provoni përsëri.",
  "Workbook column translations are incomplete. Retry report generation.":
    "Përkthimet e kolonave të Excel-it nuk janë të plota. Provoni përsëri.",
  "Workbook scope and filter translations are incomplete. Retry report generation.":
    "Përkthimet e shtrirjes dhe filtrave nuk janë të plota. Provoni përsëri.",
  "Stop the report before deleting it.":
    "Ndërpriteni raportin para se ta fshini.",
  "Stop reports in the trash before emptying it.":
    "Ndërprisni raportet në kosh para se ta zbrazni.",
  "Invalid saved report identifier.":
    "Identifikuesi i raportit të ruajtur nuk është i vlefshëm.",
  "Report files could not be removed. The trash was retained; retry after checking storage permissions.":
    "Skedarët e raporteve nuk u fshinë. Koshi u ruajt; kontrolloni lejet e ruajtjes dhe provoni përsëri.",
  "Report data collection failed. Check source status and query permissions.":
    "Mbledhja e të dhënave dështoi. Kontrolloni gjendjen e burimit dhe lejet e pyetjes.",
  "ChatGPT could not finish the report narrative. Check your subscription and retry.":
    "ChatGPT nuk përfundoi tekstin e raportit. Kontrolloni abonimin dhe provoni përsëri.",
  "Excel workbook creation failed. Retry the report or contact the administrator.":
    "Krijimi i Excel-it dështoi. Provoni përsëri ose kontaktoni administratorin.",
  "An additional analysis exceeded the row limit. Aggregate or narrow its filters.":
    "Një analizë shtesë tejkaloi kufirin e rreshtave. Përmblidhni të dhënat ose ngushtoni filtrat.",
  "Report measures must refer to numeric result columns.":
    "Treguesit e raportit duhet të përdorin kolona numerike nga rezultatet.",
  "Report dimension is not a result column.":
    "Kolona e grupimit nuk gjendet në rezultatet e raportit.",
  "A trend requires a dated result dimension.":
    "Analiza e prirjes kërkon një kolonë me data në rezultate.",
  "Trend periods must be populated and unique. Aggregate by period first.":
    "Periudhat e prirjes duhet të kenë data dhe të mos përsëriten. Përmblidhni të dhënat sipas periudhës.",
  "Profit and margin require matching revenue and cost columns.":
    "Fitimi dhe marzhi kërkojnë kolona të ardhurash dhe kostosh me të njëjtën bazë.",
  "Report column labels must be unique.":
    "Emrat e kolonave të raportit nuk duhet të përsëriten.",
  "Wait for your report to finish, or interrupt it first.":
    "Prisni përfundimin e raportit ose ndërpriteni fillimisht.",
  "Report generation was interrupted by the user.":
    "Gjenerimi i raportit u ndërpre nga përdoruesi.",
  "The selected SQL table/view references an unavailable object. Check the view definition and access to its dependencies; the database connection itself is working.":
    "Tabela ose pamja (view) e zgjedhur referon një objekt që SQL Server nuk e gjen. Kontrolloni përkufizimin e pamjes dhe qasjen te tabelat prej të cilave varet. Lidhja me databazën funksionon.",
  "A query column is unavailable. Refresh the table schema and use the current column names.":
    "Një kolonë e pyetjes nuk është e disponueshme. Rifreskoni strukturën e tabelës dhe përdorni emrat aktualë.",
  "SQL Server reported a numeric overflow. Narrow the query or use a suitable numeric type.":
    "SQL Server raportoi tejkalim numerik. Kufizoni pyetjen ose përdorni një tip numerik të përshtatshëm.",
  "Email or password is incorrect.": "Emaili ose fjalëkalimi është i pasaktë.",
  "Sign in to your workspace first.": "Hyni në hapësirën tuaj për të vazhduar.",
  "Administrator access is required.": "Kërkohet qasje administratori.",
  "Too many sign-in attempts. Try again in five minutes.":
    "Shumë tentativa hyrjeje. Provoni përsëri pas pesë minutash.",
  "Failed to fetch": "Lidhja me serverin dështoi.",
  "Local speech transcription is unavailable. Install requirements-voice.txt and enable VOICE_ENABLED.":
    "Transkriptimi zanor nuk është aktiv. Kontrolloni shërbimin e zërit dhe VOICE_ENABLED në server.",
  "Local transcription failed. Check the recording, model download, and server resources.":
    "Transkriptimi dështoi. Kontrolloni audion, shkarkimin e modelit dhe burimet e serverit.",
  "Recording is empty.": "Regjistrimi është bosh.",
  "Recording is too large. Keep recordings under 12 MB.":
    "Regjistrimi është shumë i madh. Përdorni audio më të vogël se 12 MB.",
  "Stop active responses before disconnecting.":
    "Ndaloni përgjigjet aktive para se të shkëputni llogarinë.",
  "Stop the current response before deleting this conversation.":
    "Ndaloni përgjigjen aktuale para se të fshini bisedën.",
  "The subscription connection timed out. Try again.":
    "Lidhja me abonimin tejkaloi kohën e pritjes. Provoni përsëri.",
  "Invalid email or password.": "Emaili ose fjalëkalimi është i pasaktë.",
  "Authentication required.": "Duhet të hyni në llogari.",
  "Sign in to continue.": "Hyni në llogari për të vazhduar.",
  "Administrator access required.": "Kërkohet qasje administratori.",
  "Missing connection settings:": "Mungojnë cilësimet e lidhjes:",
  "Missing backend environment variables:": "Mungojnë cilësimet e serverit:",
  "SQL Server authentication failed. Check SQLSERVER_USER and SQLSERVER_PASSWORD.":
    "Hyrja në SQL Server dështoi. Kontrolloni SQLSERVER_USER dhe SQLSERVER_PASSWORD.",
  "The configured database could not be opened. Check SQLSERVER_DATABASE and login access.":
    "Databaza nuk u hap. Kontrolloni SQLSERVER_DATABASE dhe qasjen e përdoruesit SQL.",
  "SQL Server denied access. Grant the reporting account SELECT on the approved tables/views.":
    "SQL Server refuzoi qasjen. Përdoruesi i raporteve duhet të ketë leje SELECT mbi tabelat ose pamjet.",
  "SQL Server TLS negotiation failed. Check the server encryption and certificate configuration.":
    "Lidhja e sigurt me SQL Server dështoi. Kontrolloni enkriptimin dhe certifikatën e serverit.",
  "SQL Server timed out. Check the host, port, firewall, and query performance.":
    "Lidhja me SQL Server tejkaloi kohën e pritjes. Kontrolloni adresën, portën, rrjetin dhe performancën e pyetjes.",
  "SQL Server could not complete the request. Check connectivity, database permissions, and the approved query script.":
    "SQL Server nuk e përfundoi kërkesën. Kontrolloni lidhjen, lejet e databazës dhe pyetjen.",
  "Complete the connection settings:": "Plotësoni cilësimet e lidhjes:",
  "Connect your ChatGPT subscription before sending a message.":
    "Lidhni abonimin ChatGPT para se të dërgoni mesazh.",
  "Report generation failed. Check your subscription connection and retry with valid data.":
    "Krijimi i raportit dështoi. Kontrolloni lidhjen me abonimin dhe provoni përsëri me të dhëna të vlefshme.",
  "The dataset returned no rows for these parameters. No business figures are available to report.":
    "Nuk u gjetën rreshta për këta parametra. Nuk ka të dhëna biznesi për raportin.",
  "No reporting data is available yet. Add manual JSON rows or connect a database later.":
    "Nuk ka të dhëna për raportin. Lidhni një databazë ose shtoni rreshta JSON.",
  "The database credential key is missing. Restore it from the server backup.":
    "Mungon çelësi i kredencialeve të databazës. Rikthejeni nga kopja rezervë e serverit.",
  "Saved database credentials could not be decrypted. Check the server credential key.":
    "Kredencialet e ruajtura nuk u lexuan. Kontrolloni çelësin e enkriptimit në server.",
  "The database credential key cannot be read. Check the private data volume.":
    "Çelësi i kredencialeve nuk mund të lexohet. Kontrolloni volumin privat të të dhënave.",
  "Wait for this response to finish, or stop it first.":
    "Prisni të përfundojë përgjigjja ose ndalojeni.",
  "Conversation not found.": "Biseda nuk u gjet.",
  "Source not found.": "Burimi nuk u gjet.",
  "This database is not connected yet. An administrator must configure its connector and enable the dataset.":
    "Databaza nuk është lidhur. Administratori duhet të konfigurojë lidhjen dhe të aktivizojë dataset-in opsional.",
  "A user with that email already exists.":
    "Ekziston një përdorues me këtë email.",
  "Database source is unavailable or access was not granted.":
    "Burimi nuk është i disponueshëm ose nuk keni qasje.",
  "Dataset parameters do not match the registered schema.":
    "Parametrat nuk përputhen me kërkesat e dataset-it.",
  "Application restarted during generation.":
    "Aplikacioni u rinis gjatë krijimit të raportit.",
  "Use a password with at least 12 characters.":
    "Përdorni një fjalëkalim me të paktën 12 karaktere.",
};
export function errorMessage(value: string): string {
  for (const [english, albanian] of Object.entries(errors)) {
    if (value.includes(english)) return value.replace(english, albanian);
  }
  return value;
}
export function auditLabel(action: string): string {
  const events: Record<string, string> = {
    "auth.setup": "Krijimi i hapësirës",
    "auth.login": "Hyrje në llogari",
    "auth.logout": "Dalje nga llogaria",
    "source.created": "Burim i shtuar",
    "source.updated": "Burim i ndryshuar",
    "source.checked": "Lidhje e kontrolluar",
    "source.connected": "Lidhje e riaktivizuar",
    "source.disconnected": "Lidhje e shkëputur",
    "source.removed": "Lidhje e hequr",
    "source.granted": "Qasje në databazë e dhënë",
    "source.revoked": "Qasje në databazë e hequr",
    "dataset.created": "Dataset i shtuar",
    "dataset.updated": "Dataset i ndryshuar",
    "dataset.granted": "Qasje në dataset e dhënë",
    "dataset.revoked": "Qasje në dataset e hequr",
    "report.requested": "Raport i kërkuar",
    "report.completed": "Raport i përfunduar",
    "report.workbook_validated": "Excel-i u kontrollua me të dhënat burimore",
    "report.script_retry": "Përpjekje për korrigjimin e skriptit të Excel-it",
    "report.deleted": "Raport i fshirë",
    "report.restored": "Raport i rikthyer",
    "report.trash_emptied": "Koshi i raporteve u zbraz",
    "report.failed": "Raport i dështuar",
    "reporting.tool": "Analizë e të dhënave",
    "chat.response": "Përgjigje në bisedë",
    "conversation.deleted": "Bisedë e fshirë",
    "attachment.uploaded": "Skedar i ngarkuar",
    "user.created": "Anëtar i shtuar",
    "user.updated": "Anëtar i ndryshuar",
    "runtime.restarted": "Lidhje e rinisur",
    "subscription.connected": "Abonim i lidhur",
    "subscription.disconnected": "Abonim i shkëputur",
  };
  return events[action] || action;
}

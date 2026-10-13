const labels: Record<string, string> = {
  gathering: "Duke mbledhur të dhënat",
  analyzing: "Duke analizuar të dhënat",
  excel: "Duke krijuar Excel-in dhe grafikët",
  connected: "I lidhur",
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
  "Executive overview": "Përmbledhje për drejtuesit",
  "Sales performance": "Performanca e shitjeve",
  "Operations brief": "Përmbledhje e operacioneve",
  "Connection check": "Kontrolli i lidhjes",
  "Database table and column catalog": "Katalogu i tabelave dhe kolonave",
};
export const label = (value: string) => labels[value] || value;
const errors: Record<string, string> = {
  "Stop the report before deleting it.":
    "Ndërpriteni raportin para se ta fshini.",
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
    "source.granted": "Qasje në databazë e dhënë",
    "source.revoked": "Qasje në databazë e hequr",
    "dataset.created": "Dataset i shtuar",
    "dataset.updated": "Dataset i ndryshuar",
    "dataset.granted": "Qasje në dataset e dhënë",
    "dataset.revoked": "Qasje në dataset e hequr",
    "report.requested": "Raport i kërkuar",
    "report.completed": "Raport i përfunduar",
    "report.deleted": "Raport i fshirë",
    "report.restored": "Raport i rikthyer",
    "report.failed": "Raport i dështuar",
    "reporting.tool": "Analizë e të dhënave",
    "chat.response": "Përgjigje në bisedë",
    "conversation.deleted": "Bisedë e fshirë",
    "user.created": "Anëtar i shtuar",
    "user.updated": "Anëtar i ndryshuar",
    "runtime.restarted": "Lidhje e rinisur",
    "subscription.connected": "Abonim i lidhur",
    "subscription.disconnected": "Abonim i shkëputur",
  };
  return events[action] || action;
}

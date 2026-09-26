(() => {
  "use strict";

  const UI_KEYS = [
    "my_files", "recent", "favorites", "storage", "terms", "privacy", "login_settings", "logout", "search", "create",
    "new_folder", "upload_files", "name", "size", "modified", "folder", "open", "share", "rename", "delete",
    "download", "star", "unstar", "empty_folder", "empty_folder_hint", "share_title", "add_person", "email", "role", "viewer",
    "editor", "add", "people_with_access", "owner", "general_access", "restricted", "anyone_with_link", "restricted_hint", "anyone_hint", "link_settings",
    "require_password", "link_password", "password_min", "expires_at", "invalidate_sessions", "save_settings", "copy_link", "done", "theme", "language",
    "dark_theme", "light_theme", "interface_settings", "save", "back_to_files"
  ];

  const AUTH_KEYS = [
    "login", "login_to", "username_or_email", "password", "continue", "forgot_username", "forgot_password", "no_account", "register", "create_account",
    "username", "repeat_password", "confirm_email", "verification_code", "sign_in", "resend_code", "account", "profile", "verified_email", "delete_account", "delete_account_hint"
  ];

  const KEYS = UI_KEYS.concat(AUTH_KEYS);
  const CATALOG = Object.create(null);

  function add(locale, ui, auth) {
    if (ui.length !== UI_KEYS.length || auth.length !== AUTH_KEYS.length) {
      throw new Error(`Invalid i18n catalog length for ${locale}`);
    }
    const messages = ui.concat(auth);
    CATALOG[locale] = Object.fromEntries(KEYS.map((key, index) => [key, messages[index]]));
  }

  add("ru", [
    "Мои файлы", "Недавние", "Избранное", "Хранилище", "Условия использования", "Конфиденциальность", "Настройки входа", "Выйти", "Поиск", "Создать",
    "Новая папка", "Загрузить файлы", "Название", "Размер", "Изменено", "Папка", "Открыть", "Поделиться", "Переименовать", "Удалить",
    "Скачать", "Добавить в избранное", "Убрать из избранного", "Папка пуста", "Загрузите файлы или создайте папку", "Поделиться: {name}", "Добавить пользователя", "Электронная почта", "Роль", "Читатель",
    "Редактор", "Добавить", "Пользователи с доступом", "Владелец", "Общий доступ", "Ограниченный доступ", "Все, у кого есть ссылка", "Доступ есть только у добавленных пользователей", "Открыть сможет любой, у кого есть ссылка", "Настройки ссылки",
    "Требовать пароль", "Пароль для ссылки", "Не менее 8 символов", "Срок действия", "Завершить действующие сеансы", "Сохранить настройки", "Копировать ссылку", "Готово", "Тема", "Язык",
    "Тёмная тема", "Светлая тема", "Настройки интерфейса", "Сохранить", "Назад к файлам"
  ], [
    "Вход", "Войти в {name}", "Логин или электронная почта", "Пароль", "Продолжить", "Не помню логин", "Забыли пароль?", "Нет аккаунта?", "Зарегистрироваться", "Создать аккаунт",
    "Логин", "Повторите пароль", "Подтвердите почту", "Код подтверждения", "Войти", "Отправить код ещё раз", "Аккаунт", "Профиль", "Подтверждённая почта", "Удалить аккаунт", "Аккаунт будет окончательно удалён через 30 дней"
  ]);

  add("en", [
    "My files", "Recent", "Favorites", "Storage", "Terms", "Privacy", "Sign-in settings", "Log out", "Search", "Create",
    "New folder", "Upload files", "Name", "Size", "Modified", "Folder", "Open", "Share", "Rename", "Delete",
    "Download", "Add to favorites", "Remove from favorites", "This folder is empty", "Upload files or create a folder", "Share {name}", "Add person", "Email", "Role", "Viewer",
    "Editor", "Add", "People with access", "Owner", "General access", "Restricted", "Anyone with the link", "Only people added can open this item", "Anyone with the link can open this item", "Link settings",
    "Require password", "Link password", "At least 8 characters", "Expires", "Sign out existing unlock sessions", "Save settings", "Copy link", "Done", "Theme", "Language",
    "Dark theme", "Light theme", "Interface settings", "Save", "Back to files"
  ], [
    "Log in", "Log in to {name}", "Username or email", "Password", "Continue", "Forgot username", "Forgot password?", "No account?", "Register", "Create account",
    "Username", "Repeat password", "Confirm your email", "Verification code", "Sign in", "Resend code", "Account", "Profile", "Verified email", "Delete account", "Your account will be permanently deleted after 30 days"
  ]);

  add("bg", [
    "Моите файлове", "Скорошни", "Любими", "Хранилище", "Условия за ползване", "Поверителност", "Настройки за вход", "Изход", "Търсене", "Създаване",
    "Нова папка", "Качване на файлове", "Име", "Размер", "Променено", "Папка", "Отваряне", "Споделяне", "Преименуване", "Изтриване",
    "Изтегляне", "Добавяне към любими", "Премахване от любими", "Тази папка е празна", "Качете файлове или създайте папка", "Споделяне на {name}", "Добавяне на човек", "Имейл", "Роля", "Преглеждащ",
    "Редактор", "Добавяне", "Хора с достъп", "Собственик", "Общ достъп", "Ограничен", "Всеки с връзката", "Само добавените хора могат да отворят този елемент", "Всеки с връзката може да отвори този елемент", "Настройки на връзката",
    "Изискване на парола", "Парола за връзката", "Поне 8 знака", "Изтича на", "Прекратяване на съществуващите сесии", "Запазване на настройките", "Копиране на връзката", "Готово", "Тема", "Език",
    "Тъмна тема", "Светла тема", "Настройки на интерфейса", "Запазване", "Назад към файловете"
  ], [
    "Вход", "Вход в {name}", "Потребителско име или имейл", "Парола", "Продължаване", "Забравено потребителско име", "Забравена парола?", "Нямате акаунт?", "Регистрация", "Създаване на акаунт",
    "Потребителско име", "Повторете паролата", "Потвърдете имейла си", "Код за потвърждение", "Влизане", "Повторно изпращане на кода", "Акаунт", "Профил", "Потвърден имейл", "Изтриване на акаунта", "Акаунтът ви ще бъде изтрит окончателно след 30 дни"
  ]);

  add("hr", [
    "Moje datoteke", "Nedavno", "Omiljeno", "Pohrana", "Uvjeti korištenja", "Privatnost", "Postavke prijave", "Odjava", "Pretraži", "Izradi",
    "Nova mapa", "Prenesi datoteke", "Naziv", "Veličina", "Izmijenjeno", "Mapa", "Otvori", "Dijeli", "Preimenuj", "Izbriši",
    "Preuzmi", "Dodaj u omiljeno", "Ukloni iz omiljenog", "Ova je mapa prazna", "Prenesite datoteke ili izradite mapu", "Dijeli {name}", "Dodaj osobu", "E-pošta", "Uloga", "Pregledavatelj",
    "Uređivač", "Dodaj", "Osobe s pristupom", "Vlasnik", "Opći pristup", "Ograničeno", "Svatko s poveznicom", "Samo dodane osobe mogu otvoriti ovu stavku", "Svatko s poveznicom može otvoriti ovu stavku", "Postavke poveznice",
    "Zahtijevaj lozinku", "Lozinka poveznice", "Najmanje 8 znakova", "Istječe", "Odjavi postojeće otključane sesije", "Spremi postavke", "Kopiraj poveznicu", "Gotovo", "Tema", "Jezik",
    "Tamna tema", "Svijetla tema", "Postavke sučelja", "Spremi", "Natrag na datoteke"
  ], [
    "Prijava", "Prijava u {name}", "Korisničko ime ili e-pošta", "Lozinka", "Nastavi", "Zaboravljeno korisničko ime", "Zaboravili ste lozinku?", "Nemate račun?", "Registriraj se", "Izradi račun",
    "Korisničko ime", "Ponovite lozinku", "Potvrdite e-poštu", "Kontrolni kod", "Prijavi se", "Ponovno pošalji kod", "Račun", "Profil", "Potvrđena e-pošta", "Izbriši račun", "Vaš će račun biti trajno izbrisan nakon 30 dana"
  ]);

  add("cs", [
    "Moje soubory", "Nedávné", "Oblíbené", "Úložiště", "Podmínky použití", "Soukromí", "Nastavení přihlášení", "Odhlásit se", "Hledat", "Vytvořit",
    "Nová složka", "Nahrát soubory", "Název", "Velikost", "Upraveno", "Složka", "Otevřít", "Sdílet", "Přejmenovat", "Smazat",
    "Stáhnout", "Přidat k oblíbeným", "Odebrat z oblíbených", "Tato složka je prázdná", "Nahrajte soubory nebo vytvořte složku", "Sdílet {name}", "Přidat osobu", "E-mail", "Role", "Čtenář",
    "Editor", "Přidat", "Lidé s přístupem", "Vlastník", "Obecný přístup", "Omezeno", "Kdokoli s odkazem", "Tuto položku mohou otevřít jen přidané osoby", "Tuto položku může otevřít kdokoli s odkazem", "Nastavení odkazu",
    "Vyžadovat heslo", "Heslo odkazu", "Alespoň 8 znaků", "Platnost vyprší", "Odhlásit stávající odemčené relace", "Uložit nastavení", "Kopírovat odkaz", "Hotovo", "Motiv", "Jazyk",
    "Tmavý motiv", "Světlý motiv", "Nastavení rozhraní", "Uložit", "Zpět k souborům"
  ], [
    "Přihlášení", "Přihlášení do {name}", "Uživatelské jméno nebo e-mail", "Heslo", "Pokračovat", "Zapomenuté uživatelské jméno", "Zapomněli jste heslo?", "Nemáte účet?", "Registrovat se", "Vytvořit účet",
    "Uživatelské jméno", "Zopakujte heslo", "Potvrďte svůj e-mail", "Ověřovací kód", "Přihlásit se", "Znovu odeslat kód", "Účet", "Profil", "Ověřený e-mail", "Smazat účet", "Váš účet bude po 30 dnech trvale smazán"
  ]);

  add("da", [
    "Mine filer", "Seneste", "Favoritter", "Lagerplads", "Vilkår", "Privatliv", "Loginindstillinger", "Log ud", "Søg", "Opret",
    "Ny mappe", "Upload filer", "Navn", "Størrelse", "Ændret", "Mappe", "Åbn", "Del", "Omdøb", "Slet",
    "Download", "Føj til favoritter", "Fjern fra favoritter", "Denne mappe er tom", "Upload filer, eller opret en mappe", "Del {name}", "Tilføj person", "E-mail", "Rolle", "Seer",
    "Redaktør", "Tilføj", "Personer med adgang", "Ejer", "Generel adgang", "Begrænset", "Alle med linket", "Kun tilføjede personer kan åbne dette element", "Alle med linket kan åbne dette element", "Linkindstillinger",
    "Kræv adgangskode", "Adgangskode til link", "Mindst 8 tegn", "Udløber", "Log eksisterende oplåste sessioner ud", "Gem indstillinger", "Kopiér link", "Udført", "Tema", "Sprog",
    "Mørkt tema", "Lyst tema", "Indstillinger for brugerfladen", "Gem", "Tilbage til filer"
  ], [
    "Log ind", "Log ind på {name}", "Brugernavn eller e-mail", "Adgangskode", "Fortsæt", "Glemt brugernavn", "Glemt adgangskode?", "Ingen konto?", "Tilmeld dig", "Opret konto",
    "Brugernavn", "Gentag adgangskode", "Bekræft din e-mail", "Bekræftelseskode", "Log ind", "Send koden igen", "Konto", "Profil", "Bekræftet e-mail", "Slet konto", "Din konto slettes permanent efter 30 dage"
  ]);

  add("nl", [
    "Mijn bestanden", "Recent", "Favorieten", "Opslag", "Voorwaarden", "Privacy", "Inloginstellingen", "Uitloggen", "Zoeken", "Maken",
    "Nieuwe map", "Bestanden uploaden", "Naam", "Grootte", "Gewijzigd", "Map", "Openen", "Delen", "Naam wijzigen", "Verwijderen",
    "Downloaden", "Toevoegen aan favorieten", "Verwijderen uit favorieten", "Deze map is leeg", "Upload bestanden of maak een map", "{name} delen", "Persoon toevoegen", "E-mail", "Rol", "Lezer",
    "Bewerker", "Toevoegen", "Mensen met toegang", "Eigenaar", "Algemene toegang", "Beperkt", "Iedereen met de link", "Alleen toegevoegde personen kunnen dit item openen", "Iedereen met de link kan dit item openen", "Linkinstellingen",
    "Wachtwoord vereisen", "Wachtwoord voor link", "Minimaal 8 tekens", "Verloopt op", "Bestaande ontgrendelde sessies afmelden", "Instellingen opslaan", "Link kopiëren", "Gereed", "Thema", "Taal",
    "Donker thema", "Licht thema", "Interface-instellingen", "Opslaan", "Terug naar bestanden"
  ], [
    "Inloggen", "Inloggen bij {name}", "Gebruikersnaam of e-mail", "Wachtwoord", "Doorgaan", "Gebruikersnaam vergeten", "Wachtwoord vergeten?", "Geen account?", "Registreren", "Account maken",
    "Gebruikersnaam", "Wachtwoord herhalen", "Bevestig je e-mailadres", "Verificatiecode", "Inloggen", "Code opnieuw verzenden", "Account", "Profiel", "Geverifieerd e-mailadres", "Account verwijderen", "Je account wordt na 30 dagen definitief verwijderd"
  ]);

  add("et", [
    "Minu failid", "Hiljutised", "Lemmikud", "Salvestusruum", "Tingimused", "Privaatsus", "Sisselogimise seaded", "Logi välja", "Otsi", "Loo",
    "Uus kaust", "Laadi failid üles", "Nimi", "Suurus", "Muudetud", "Kaust", "Ava", "Jaga", "Nimeta ümber", "Kustuta",
    "Laadi alla", "Lisa lemmikutesse", "Eemalda lemmikutest", "See kaust on tühi", "Laadi failid üles või loo kaust", "Jaga: {name}", "Lisa inimene", "E-post", "Roll", "Vaataja",
    "Muutja", "Lisa", "Juurdepääsuga inimesed", "Omanik", "Üldine juurdepääs", "Piiratud", "Kõik, kellel on link", "Selle üksuse saavad avada ainult lisatud inimesed", "Selle üksuse saab avada igaüks, kellel on link", "Lingi seaded",
    "Nõua parooli", "Lingi parool", "Vähemalt 8 märki", "Aegub", "Logi olemasolevad avatud seansid välja", "Salvesta seaded", "Kopeeri link", "Valmis", "Kujundus", "Keel",
    "Tume kujundus", "Hele kujundus", "Kasutajaliidese seaded", "Salvesta", "Tagasi failide juurde"
  ], [
    "Logi sisse", "Logi sisse teenusesse {name}", "Kasutajanimi või e-post", "Parool", "Jätka", "Kasutajanimi ununes", "Parool ununes?", "Kontot pole?", "Registreeru", "Loo konto",
    "Kasutajanimi", "Korda parooli", "Kinnita oma e-post", "Kinnituskood", "Logi sisse", "Saada kood uuesti", "Konto", "Profiil", "Kinnitatud e-post", "Kustuta konto", "Sinu konto kustutatakse jäädavalt 30 päeva pärast"
  ]);

  add("fi", [
    "Omat tiedostot", "Viimeisimmät", "Suosikit", "Tallennustila", "Käyttöehdot", "Tietosuoja", "Kirjautumisasetukset", "Kirjaudu ulos", "Haku", "Luo",
    "Uusi kansio", "Lataa tiedostoja", "Nimi", "Koko", "Muokattu", "Kansio", "Avaa", "Jaa", "Nimeä uudelleen", "Poista",
    "Lataa", "Lisää suosikkeihin", "Poista suosikeista", "Tämä kansio on tyhjä", "Lataa tiedostoja tai luo kansio", "Jaa {name}", "Lisää henkilö", "Sähköposti", "Rooli", "Katselija",
    "Muokkaaja", "Lisää", "Käyttöoikeuden saaneet", "Omistaja", "Yleinen käyttöoikeus", "Rajoitettu", "Kaikki linkin saaneet", "Vain lisätyt henkilöt voivat avata tämän kohteen", "Kaikki linkin saaneet voivat avata tämän kohteen", "Linkin asetukset",
    "Vaadi salasana", "Linkin salasana", "Vähintään 8 merkkiä", "Vanhenee", "Kirjaa ulos nykyiset avatut istunnot", "Tallenna asetukset", "Kopioi linkki", "Valmis", "Teema", "Kieli",
    "Tumma teema", "Vaalea teema", "Käyttöliittymän asetukset", "Tallenna", "Takaisin tiedostoihin"
  ], [
    "Kirjaudu sisään", "Kirjaudu palveluun {name}", "Käyttäjänimi tai sähköposti", "Salasana", "Jatka", "Unohditko käyttäjänimen", "Unohditko salasanan?", "Ei tiliä?", "Rekisteröidy", "Luo tili",
    "Käyttäjänimi", "Toista salasana", "Vahvista sähköpostiosoitteesi", "Vahvistuskoodi", "Kirjaudu sisään", "Lähetä koodi uudelleen", "Tili", "Profiili", "Vahvistettu sähköposti", "Poista tili", "Tilisi poistetaan pysyvästi 30 päivän kuluttua"
  ]);

  add("fr", [
    "Mes fichiers", "Récents", "Favoris", "Espace de stockage", "Conditions d’utilisation", "Confidentialité", "Paramètres de connexion", "Se déconnecter", "Rechercher", "Créer",
    "Nouveau dossier", "Importer des fichiers", "Nom", "Taille", "Modification", "Dossier", "Ouvrir", "Partager", "Renommer", "Supprimer",
    "Télécharger", "Ajouter aux favoris", "Retirer des favoris", "Ce dossier est vide", "Importez des fichiers ou créez un dossier", "Partager {name}", "Ajouter une personne", "Adresse e-mail", "Rôle", "Lecteur",
    "Éditeur", "Ajouter", "Personnes ayant accès", "Propriétaire", "Accès général", "Accès limité", "Tous les détenteurs du lien", "Seules les personnes ajoutées peuvent ouvrir cet élément", "Toute personne disposant du lien peut ouvrir cet élément", "Paramètres du lien",
    "Exiger un mot de passe", "Mot de passe du lien", "8 caractères minimum", "Date d’expiration", "Déconnecter les sessions déjà déverrouillées", "Enregistrer les paramètres", "Copier le lien", "Terminé", "Thème", "Langue",
    "Thème sombre", "Thème clair", "Paramètres de l’interface", "Enregistrer", "Retour aux fichiers"
  ], [
    "Connexion", "Se connecter à {name}", "Nom d’utilisateur ou e-mail", "Mot de passe", "Continuer", "Nom d’utilisateur oublié", "Mot de passe oublié ?", "Pas de compte ?", "S’inscrire", "Créer un compte",
    "Nom d’utilisateur", "Répétez le mot de passe", "Confirmez votre adresse e-mail", "Code de vérification", "Se connecter", "Renvoyer le code", "Compte", "Profil", "Adresse e-mail vérifiée", "Supprimer le compte", "Votre compte sera définitivement supprimé après 30 jours"
  ]);

  add("de", [
    "Meine Dateien", "Zuletzt verwendet", "Favoriten", "Speicher", "Nutzungsbedingungen", "Datenschutz", "Anmeldeeinstellungen", "Abmelden", "Suchen", "Erstellen",
    "Neuer Ordner", "Dateien hochladen", "Name", "Größe", "Geändert", "Ordner", "Öffnen", "Teilen", "Umbenennen", "Löschen",
    "Herunterladen", "Zu Favoriten hinzufügen", "Aus Favoriten entfernen", "Dieser Ordner ist leer", "Dateien hochladen oder einen Ordner erstellen", "{name} teilen", "Person hinzufügen", "E-Mail", "Rolle", "Betrachter",
    "Bearbeiter", "Hinzufügen", "Personen mit Zugriff", "Eigentümer", "Allgemeiner Zugriff", "Eingeschränkt", "Jeder mit dem Link", "Nur hinzugefügte Personen können dieses Element öffnen", "Jeder mit dem Link kann dieses Element öffnen", "Linkeinstellungen",
    "Passwort erforderlich", "Link-Passwort", "Mindestens 8 Zeichen", "Läuft ab", "Bestehende entsperrte Sitzungen abmelden", "Einstellungen speichern", "Link kopieren", "Fertig", "Design", "Sprache",
    "Dunkles Design", "Helles Design", "Oberflächeneinstellungen", "Speichern", "Zurück zu den Dateien"
  ], [
    "Anmelden", "Bei {name} anmelden", "Benutzername oder E-Mail", "Passwort", "Weiter", "Benutzername vergessen", "Passwort vergessen?", "Noch kein Konto?", "Registrieren", "Konto erstellen",
    "Benutzername", "Passwort wiederholen", "E-Mail-Adresse bestätigen", "Bestätigungscode", "Anmelden", "Code erneut senden", "Konto", "Profil", "Bestätigte E-Mail-Adresse", "Konto löschen", "Dein Konto wird nach 30 Tagen endgültig gelöscht"
  ]);

  add("el", [
    "Τα αρχεία μου", "Πρόσφατα", "Αγαπημένα", "Αποθηκευτικός χώρος", "Όροι χρήσης", "Απόρρητο", "Ρυθμίσεις σύνδεσης", "Αποσύνδεση", "Αναζήτηση", "Δημιουργία",
    "Νέος φάκελος", "Μεταφόρτωση αρχείων", "Όνομα", "Μέγεθος", "Τροποποιήθηκε", "Φάκελος", "Άνοιγμα", "Κοινοποίηση", "Μετονομασία", "Διαγραφή",
    "Λήψη", "Προσθήκη στα αγαπημένα", "Κατάργηση από τα αγαπημένα", "Αυτός ο φάκελος είναι κενός", "Μεταφορτώστε αρχεία ή δημιουργήστε φάκελο", "Κοινοποίηση {name}", "Προσθήκη ατόμου", "Ηλεκτρονικό ταχυδρομείο", "Ρόλος", "Αναγνώστης",
    "Συντάκτης", "Προσθήκη", "Άτομα με πρόσβαση", "Κάτοχος", "Γενική πρόσβαση", "Περιορισμένη", "Όλοι όσοι έχουν τον σύνδεσμο", "Μόνο τα άτομα που προστέθηκαν μπορούν να ανοίξουν αυτό το στοιχείο", "Όλοι όσοι έχουν τον σύνδεσμο μπορούν να ανοίξουν αυτό το στοιχείο", "Ρυθμίσεις συνδέσμου",
    "Απαίτηση κωδικού πρόσβασης", "Κωδικός συνδέσμου", "Τουλάχιστον 8 χαρακτήρες", "Λήγει", "Αποσύνδεση υπαρχουσών ξεκλείδωτων συνεδριών", "Αποθήκευση ρυθμίσεων", "Αντιγραφή συνδέσμου", "Τέλος", "Θέμα", "Γλώσσα",
    "Σκούρο θέμα", "Ανοιχτό θέμα", "Ρυθμίσεις περιβάλλοντος", "Αποθήκευση", "Πίσω στα αρχεία"
  ], [
    "Σύνδεση", "Σύνδεση στο {name}", "Όνομα χρήστη ή email", "Κωδικός πρόσβασης", "Συνέχεια", "Ξεχάσατε το όνομα χρήστη", "Ξεχάσατε τον κωδικό;", "Δεν έχετε λογαριασμό;", "Εγγραφή", "Δημιουργία λογαριασμού",
    "Όνομα χρήστη", "Επανάληψη κωδικού", "Επιβεβαιώστε το email σας", "Κωδικός επαλήθευσης", "Σύνδεση", "Επανάληψη αποστολής κωδικού", "Λογαριασμός", "Προφίλ", "Επαληθευμένο email", "Διαγραφή λογαριασμού", "Ο λογαριασμός σας θα διαγραφεί οριστικά μετά από 30 ημέρες"
  ]);

  add("hu", [
    "Saját fájlok", "Legutóbbiak", "Kedvencek", "Tárhely", "Feltételek", "Adatvédelem", "Bejelentkezési beállítások", "Kijelentkezés", "Keresés", "Létrehozás",
    "Új mappa", "Fájlok feltöltése", "Név", "Méret", "Módosítva", "Mappa", "Megnyitás", "Megosztás", "Átnevezés", "Törlés",
    "Letöltés", "Hozzáadás a kedvencekhez", "Eltávolítás a kedvencek közül", "Ez a mappa üres", "Töltsön fel fájlokat, vagy hozzon létre mappát", "{name} megosztása", "Személy hozzáadása", "E-mail", "Szerepkör", "Megtekintő",
    "Szerkesztő", "Hozzáadás", "Hozzáféréssel rendelkező személyek", "Tulajdonos", "Általános hozzáférés", "Korlátozott", "A link birtokában bárki", "Csak a hozzáadott személyek nyithatják meg ezt az elemet", "A link birtokában bárki megnyithatja ezt az elemet", "Linkbeállítások",
    "Jelszó megkövetelése", "Link jelszava", "Legalább 8 karakter", "Lejárat", "Meglévő feloldott munkamenetek kijelentkeztetése", "Beállítások mentése", "Link másolása", "Kész", "Téma", "Nyelv",
    "Sötét téma", "Világos téma", "Felület beállításai", "Mentés", "Vissza a fájlokhoz"
  ], [
    "Bejelentkezés", "Bejelentkezés: {name}", "Felhasználónév vagy e-mail", "Jelszó", "Tovább", "Elfelejtett felhasználónév", "Elfelejtette a jelszavát?", "Nincs fiókja?", "Regisztráció", "Fiók létrehozása",
    "Felhasználónév", "Jelszó megismétlése", "E-mail-cím megerősítése", "Ellenőrző kód", "Bejelentkezés", "Kód újraküldése", "Fiók", "Profil", "Megerősített e-mail", "Fiók törlése", "Fiókja 30 nap után véglegesen törlődik"
  ]);

  add("ga", [
    "Mo chuid comhad", "Le déanaí", "Ceanáin", "Stóras", "Téarmaí", "Príobháideachas", "Socruithe sínithe isteach", "Logáil amach", "Cuardaigh", "Cruthaigh",
    "Fillteán nua", "Uaslódáil comhaid", "Ainm", "Méid", "Athraithe", "Fillteán", "Oscail", "Comhroinn", "Athainmnigh", "Scrios",
    "Íoslódáil", "Cuir leis na ceanáin", "Bain ó na ceanáin", "Tá an fillteán seo folamh", "Uaslódáil comhaid nó cruthaigh fillteán", "Comhroinn {name}", "Cuir duine leis", "Ríomhphost", "Ról", "Amharcóir",
    "Eagarthóir", "Cuir leis", "Daoine a bhfuil rochtain acu", "Úinéir", "Rochtain ghinearálta", "Srianta", "Aon duine a bhfuil an nasc aige", "Ní féidir ach le daoine curtha leis an mhír seo a oscailt", "Is féidir le haon duine a bhfuil an nasc aige an mhír seo a oscailt", "Socruithe naisc",
    "Éiligh pasfhocal", "Pasfhocal an naisc", "8 gcarachtar ar a laghad", "In éag", "Logáil amach seisiúin dhíghlasáilte reatha", "Sábháil socruithe", "Cóipeáil nasc", "Déanta", "Téama", "Teanga",
    "Téama dorcha", "Téama geal", "Socruithe comhéadain", "Sábháil", "Ar ais chuig comhaid"
  ], [
    "Logáil isteach", "Logáil isteach ar {name}", "Ainm úsáideora nó ríomhphost", "Pasfhocal", "Lean ar aghaidh", "Ainm úsáideora dearmadta", "Pasfhocal dearmadta?", "Gan chuntas?", "Cláraigh", "Cruthaigh cuntas",
    "Ainm úsáideora", "Déan an pasfhocal arís", "Deimhnigh do ríomhphost", "Cód fíorúcháin", "Sínigh isteach", "Seol an cód arís", "Cuntas", "Próifíl", "Ríomhphost fíoraithe", "Scrios cuntas", "Scriosfar do chuntas go buan tar éis 30 lá"
  ]);

  add("it", [
    "I miei file", "Recenti", "Preferiti", "Spazio di archiviazione", "Termini", "Privacy", "Impostazioni di accesso", "Esci", "Cerca", "Crea",
    "Nuova cartella", "Carica file", "Nome", "Dimensioni", "Ultima modifica", "Cartella", "Apri", "Condividi", "Rinomina", "Elimina",
    "Scarica", "Aggiungi ai preferiti", "Rimuovi dai preferiti", "Questa cartella è vuota", "Carica file o crea una cartella", "Condividi {name}", "Aggiungi persona", "Email", "Ruolo", "Visualizzatore",
    "Editor", "Aggiungi", "Persone con accesso", "Proprietario", "Accesso generale", "Con limitazioni", "Chiunque abbia il link", "Solo le persone aggiunte possono aprire questo elemento", "Chiunque abbia il link può aprire questo elemento", "Impostazioni link",
    "Richiedi password", "Password del link", "Almeno 8 caratteri", "Scade il", "Disconnetti le sessioni già sbloccate", "Salva impostazioni", "Copia link", "Fine", "Tema", "Lingua",
    "Tema scuro", "Tema chiaro", "Impostazioni interfaccia", "Salva", "Torna ai file"
  ], [
    "Accedi", "Accedi a {name}", "Nome utente o email", "Password", "Continua", "Nome utente dimenticato", "Password dimenticata?", "Non hai un account?", "Registrati", "Crea account",
    "Nome utente", "Ripeti password", "Conferma la tua email", "Codice di verifica", "Accedi", "Invia di nuovo il codice", "Account", "Profilo", "Email verificata", "Elimina account", "Il tuo account verrà eliminato definitivamente dopo 30 giorni"
  ]);

  add("lv", [
    "Mani faili", "Nesenie", "Izlase", "Krātuve", "Noteikumi", "Konfidencialitāte", "Pieteikšanās iestatījumi", "Izrakstīties", "Meklēt", "Izveidot",
    "Jauna mape", "Augšupielādēt failus", "Nosaukums", "Lielums", "Mainīts", "Mape", "Atvērt", "Kopīgot", "Pārdēvēt", "Dzēst",
    "Lejupielādēt", "Pievienot izlasei", "Noņemt no izlases", "Šī mape ir tukša", "Augšupielādējiet failus vai izveidojiet mapi", "Kopīgot: {name}", "Pievienot personu", "E-pasts", "Loma", "Skatītājs",
    "Redaktors", "Pievienot", "Personas ar piekļuvi", "Īpašnieks", "Vispārīga piekļuve", "Ierobežota", "Ikviens, kam ir saite", "Šo vienumu var atvērt tikai pievienotās personas", "Šo vienumu var atvērt ikviens, kam ir saite", "Saites iestatījumi",
    "Pieprasīt paroli", "Saites parole", "Vismaz 8 rakstzīmes", "Derīguma termiņš", "Izrakstīt esošās atbloķētās sesijas", "Saglabāt iestatījumus", "Kopēt saiti", "Gatavs", "Motīvs", "Valoda",
    "Tumšais motīvs", "Gaišais motīvs", "Saskarnes iestatījumi", "Saglabāt", "Atpakaļ uz failiem"
  ], [
    "Pieteikties", "Pieteikties pakalpojumā {name}", "Lietotājvārds vai e-pasts", "Parole", "Turpināt", "Aizmirsts lietotājvārds", "Aizmirsāt paroli?", "Nav konta?", "Reģistrēties", "Izveidot kontu",
    "Lietotājvārds", "Atkārtojiet paroli", "Apstipriniet savu e-pastu", "Verifikācijas kods", "Pieteikties", "Nosūtīt kodu vēlreiz", "Konts", "Profils", "Apstiprināts e-pasts", "Dzēst kontu", "Jūsu konts tiks neatgriezeniski dzēsts pēc 30 dienām"
  ]);

  add("lt", [
    "Mano failai", "Naujausi", "Mėgstamiausi", "Saugykla", "Sąlygos", "Privatumas", "Prisijungimo nustatymai", "Atsijungti", "Ieškoti", "Kurti",
    "Naujas aplankas", "Įkelti failus", "Pavadinimas", "Dydis", "Pakeista", "Aplankas", "Atidaryti", "Bendrinti", "Pervadinti", "Ištrinti",
    "Atsisiųsti", "Pridėti prie mėgstamiausių", "Pašalinti iš mėgstamiausių", "Šis aplankas tuščias", "Įkelkite failus arba sukurkite aplanką", "Bendrinti {name}", "Pridėti asmenį", "El. paštas", "Vaidmuo", "Skaitytojas",
    "Redaktorius", "Pridėti", "Prieigą turintys žmonės", "Savininkas", "Bendroji prieiga", "Apribota", "Visi, turintys nuorodą", "Šį elementą gali atidaryti tik pridėti žmonės", "Šį elementą gali atidaryti visi, turintys nuorodą", "Nuorodos nustatymai",
    "Reikalauti slaptažodžio", "Nuorodos slaptažodis", "Bent 8 simboliai", "Galioja iki", "Atjungti esamas atrakintas sesijas", "Išsaugoti nustatymus", "Kopijuoti nuorodą", "Atlikta", "Tema", "Kalba",
    "Tamsi tema", "Šviesi tema", "Sąsajos nustatymai", "Išsaugoti", "Grįžti į failus"
  ], [
    "Prisijungti", "Prisijungti prie {name}", "Naudotojo vardas arba el. paštas", "Slaptažodis", "Tęsti", "Pamiršote naudotojo vardą", "Pamiršote slaptažodį?", "Neturite paskyros?", "Registruotis", "Sukurti paskyrą",
    "Naudotojo vardas", "Pakartokite slaptažodį", "Patvirtinkite el. paštą", "Patvirtinimo kodas", "Prisijungti", "Siųsti kodą dar kartą", "Paskyra", "Profilis", "Patvirtintas el. paštas", "Ištrinti paskyrą", "Jūsų paskyra bus visam laikui ištrinta po 30 dienų"
  ]);

  add("mt", [
    "Il-fajls tiegħi", "Riċenti", "Favoriti", "Ħażna", "Termini", "Privatezza", "Settings tad-dħul", "Oħroġ", "Fittex", "Oħloq",
    "Folder ġdid", "Tella’ fajls", "Isem", "Daqs", "Modifikat", "Folder", "Iftaħ", "Aqsam", "Ibdel l-isem", "Ħassar",
    "Niżżel", "Żid mal-favoriti", "Neħħi mill-favoriti", "Dan il-folder huwa vojt", "Tella’ fajls jew oħloq folder", "Aqsam {name}", "Żid persuna", "Email", "Rwol", "Qarrej",
    "Editur", "Żid", "Persuni b’aċċess", "Sid", "Aċċess ġenerali", "Ristrett", "Kull min għandu l-link", "Il-persuni miżjuda biss jistgħu jiftħu dan l-element", "Kull min għandu l-link jista’ jiftaħ dan l-element", "Settings tal-link",
    "Itlob password", "Password tal-link", "Mill-inqas 8 karattri", "Jiskadi", "Oħroġ mis-sessjonijiet miftuħa eżistenti", "Issejvja s-settings", "Ikkopja l-link", "Lest", "Tema", "Lingwa",
    "Tema skura", "Tema ċara", "Settings tal-interfaċċa", "Issejvja", "Lura għall-fajls"
  ], [
    "Idħol", "Idħol f’{name}", "Isem tal-utent jew email", "Password", "Kompli", "Insejt l-isem tal-utent", "Insejt il-password?", "M’għandekx kont?", "Irreġistra", "Oħloq kont",
    "Isem tal-utent", "Erġa’ daħħal il-password", "Ikkonferma l-email tiegħek", "Kodiċi ta’ verifika", "Idħol", "Erġa’ ibgħat il-kodiċi", "Kont", "Profil", "Email verifikata", "Ħassar il-kont", "Il-kont tiegħek jitħassar b’mod permanenti wara 30 jum"
  ]);

  add("pl", [
    "Moje pliki", "Ostatnie", "Ulubione", "Miejsce na dane", "Warunki", "Prywatność", "Ustawienia logowania", "Wyloguj się", "Szukaj", "Utwórz",
    "Nowy folder", "Prześlij pliki", "Nazwa", "Rozmiar", "Zmodyfikowano", "Folder", "Otwórz", "Udostępnij", "Zmień nazwę", "Usuń",
    "Pobierz", "Dodaj do ulubionych", "Usuń z ulubionych", "Ten folder jest pusty", "Prześlij pliki lub utwórz folder", "Udostępnij {name}", "Dodaj osobę", "E-mail", "Rola", "Wyświetlający",
    "Edytujący", "Dodaj", "Osoby z dostępem", "Właściciel", "Dostęp ogólny", "Ograniczony", "Każda osoba mająca link", "Tylko dodane osoby mogą otworzyć ten element", "Każda osoba mająca link może otworzyć ten element", "Ustawienia linku",
    "Wymagaj hasła", "Hasło do linku", "Co najmniej 8 znaków", "Wygasa", "Wyloguj istniejące odblokowane sesje", "Zapisz ustawienia", "Kopiuj link", "Gotowe", "Motyw", "Język",
    "Ciemny motyw", "Jasny motyw", "Ustawienia interfejsu", "Zapisz", "Wróć do plików"
  ], [
    "Logowanie", "Zaloguj się do {name}", "Nazwa użytkownika lub e-mail", "Hasło", "Dalej", "Nie pamiętam nazwy użytkownika", "Nie pamiętasz hasła?", "Nie masz konta?", "Zarejestruj się", "Utwórz konto",
    "Nazwa użytkownika", "Powtórz hasło", "Potwierdź swój adres e-mail", "Kod weryfikacyjny", "Zaloguj się", "Wyślij kod ponownie", "Konto", "Profil", "Zweryfikowany e-mail", "Usuń konto", "Twoje konto zostanie trwale usunięte po 30 dniach"
  ]);

  add("pt", [
    "Os meus ficheiros", "Recentes", "Favoritos", "Armazenamento", "Termos", "Privacidade", "Definições de início de sessão", "Terminar sessão", "Pesquisar", "Criar",
    "Nova pasta", "Carregar ficheiros", "Nome", "Tamanho", "Modificado", "Pasta", "Abrir", "Partilhar", "Mudar nome", "Eliminar",
    "Transferir", "Adicionar aos favoritos", "Remover dos favoritos", "Esta pasta está vazia", "Carregue ficheiros ou crie uma pasta", "Partilhar {name}", "Adicionar pessoa", "Email", "Função", "Leitor",
    "Editor", "Adicionar", "Pessoas com acesso", "Proprietário", "Acesso geral", "Restrito", "Qualquer pessoa com o link", "Apenas as pessoas adicionadas podem abrir este item", "Qualquer pessoa com o link pode abrir este item", "Definições do link",
    "Exigir palavra-passe", "Palavra-passe do link", "Pelo menos 8 caracteres", "Expira em", "Terminar sessões desbloqueadas existentes", "Guardar definições", "Copiar link", "Concluído", "Tema", "Idioma",
    "Tema escuro", "Tema claro", "Definições da interface", "Guardar", "Voltar aos ficheiros"
  ], [
    "Iniciar sessão", "Iniciar sessão em {name}", "Nome de utilizador ou email", "Palavra-passe", "Continuar", "Esqueci-me do nome de utilizador", "Esqueceu-se da palavra-passe?", "Não tem conta?", "Registar", "Criar conta",
    "Nome de utilizador", "Repetir palavra-passe", "Confirme o seu email", "Código de verificação", "Iniciar sessão", "Reenviar código", "Conta", "Perfil", "Email verificado", "Eliminar conta", "A sua conta será eliminada permanentemente após 30 dias"
  ]);

  add("ro", [
    "Fișierele mele", "Recente", "Favorite", "Spațiu de stocare", "Termeni", "Confidențialitate", "Setări de conectare", "Deconectare", "Caută", "Creează",
    "Dosar nou", "Încarcă fișiere", "Nume", "Dimensiune", "Modificat", "Dosar", "Deschide", "Trimite", "Redenumește", "Șterge",
    "Descarcă", "Adaugă la favorite", "Elimină din favorite", "Acest dosar este gol", "Încarcă fișiere sau creează un dosar", "Trimite {name}", "Adaugă o persoană", "E-mail", "Rol", "Vizualizator",
    "Editor", "Adaugă", "Persoane cu acces", "Proprietar", "Acces general", "Restricționat", "Oricine are linkul", "Numai persoanele adăugate pot deschide acest element", "Oricine are linkul poate deschide acest element", "Setările linkului",
    "Solicită parolă", "Parola linkului", "Cel puțin 8 caractere", "Expiră la", "Deconectează sesiunile deblocate existente", "Salvează setările", "Copiază linkul", "Gata", "Temă", "Limbă",
    "Temă întunecată", "Temă luminoasă", "Setările interfeței", "Salvează", "Înapoi la fișiere"
  ], [
    "Conectare", "Conectare la {name}", "Nume de utilizator sau e-mail", "Parolă", "Continuă", "Am uitat numele de utilizator", "Ai uitat parola?", "Nu ai cont?", "Înregistrează-te", "Creează un cont",
    "Nume de utilizator", "Repetă parola", "Confirmă adresa de e-mail", "Cod de verificare", "Conectează-te", "Retrimite codul", "Cont", "Profil", "E-mail verificat", "Șterge contul", "Contul tău va fi șters definitiv după 30 de zile"
  ]);

  add("sk", [
    "Moje súbory", "Nedávne", "Obľúbené", "Úložisko", "Podmienky", "Súkromie", "Nastavenia prihlásenia", "Odhlásiť sa", "Hľadať", "Vytvoriť",
    "Nový priečinok", "Nahrať súbory", "Názov", "Veľkosť", "Upravené", "Priečinok", "Otvoriť", "Zdieľať", "Premenovať", "Odstrániť",
    "Stiahnuť", "Pridať medzi obľúbené", "Odstrániť z obľúbených", "Tento priečinok je prázdny", "Nahrajte súbory alebo vytvorte priečinok", "Zdieľať {name}", "Pridať osobu", "E-mail", "Rola", "Čitateľ",
    "Editor", "Pridať", "Ľudia s prístupom", "Vlastník", "Všeobecný prístup", "Obmedzené", "Ktokoľvek s odkazom", "Túto položku môžu otvoriť iba pridané osoby", "Túto položku môže otvoriť ktokoľvek s odkazom", "Nastavenia odkazu",
    "Vyžadovať heslo", "Heslo odkazu", "Aspoň 8 znakov", "Platnosť vyprší", "Odhlásiť existujúce odomknuté relácie", "Uložiť nastavenia", "Kopírovať odkaz", "Hotovo", "Motív", "Jazyk",
    "Tmavý motív", "Svetlý motív", "Nastavenia rozhrania", "Uložiť", "Späť na súbory"
  ], [
    "Prihlásenie", "Prihlásenie do {name}", "Používateľské meno alebo e-mail", "Heslo", "Pokračovať", "Zabudnuté používateľské meno", "Zabudli ste heslo?", "Nemáte účet?", "Registrovať sa", "Vytvoriť účet",
    "Používateľské meno", "Zopakujte heslo", "Potvrďte svoj e-mail", "Overovací kód", "Prihlásiť sa", "Znova odoslať kód", "Účet", "Profil", "Overený e-mail", "Odstrániť účet", "Váš účet bude po 30 dňoch natrvalo odstránený"
  ]);

  add("sl", [
    "Moje datoteke", "Nedavno", "Priljubljeno", "Shramba", "Pogoji", "Zasebnost", "Nastavitve prijave", "Odjava", "Iskanje", "Ustvari",
    "Nova mapa", "Naloži datoteke", "Ime", "Velikost", "Spremenjeno", "Mapa", "Odpri", "Deli", "Preimenuj", "Izbriši",
    "Prenesi", "Dodaj med priljubljene", "Odstrani iz priljubljenih", "Ta mapa je prazna", "Naložite datoteke ali ustvarite mapo", "Deli {name}", "Dodaj osebo", "E-pošta", "Vloga", "Gledalec",
    "Urednik", "Dodaj", "Osebe z dostopom", "Lastnik", "Splošni dostop", "Omejeno", "Vsi s povezavo", "Ta element lahko odprejo samo dodane osebe", "Ta element lahko odpre vsak s povezavo", "Nastavitve povezave",
    "Zahtevaj geslo", "Geslo povezave", "Vsaj 8 znakov", "Poteče", "Odjavi obstoječe odklenjene seje", "Shrani nastavitve", "Kopiraj povezavo", "Končano", "Tema", "Jezik",
    "Temna tema", "Svetla tema", "Nastavitve vmesnika", "Shrani", "Nazaj na datoteke"
  ], [
    "Prijava", "Prijava v {name}", "Uporabniško ime ali e-pošta", "Geslo", "Nadaljuj", "Pozabljeno uporabniško ime", "Ste pozabili geslo?", "Nimate računa?", "Registracija", "Ustvari račun",
    "Uporabniško ime", "Ponovite geslo", "Potrdite svoj e-poštni naslov", "Potrditvena koda", "Prijavi se", "Znova pošlji kodo", "Račun", "Profil", "Potrjen e-poštni naslov", "Izbriši račun", "Vaš račun bo po 30 dneh trajno izbrisan"
  ]);

  add("es", [
    "Mis archivos", "Recientes", "Favoritos", "Almacenamiento", "Términos", "Privacidad", "Ajustes de inicio de sesión", "Cerrar sesión", "Buscar", "Crear",
    "Nueva carpeta", "Subir archivos", "Nombre", "Tamaño", "Modificado", "Carpeta", "Abrir", "Compartir", "Cambiar nombre", "Eliminar",
    "Descargar", "Añadir a favoritos", "Quitar de favoritos", "Esta carpeta está vacía", "Sube archivos o crea una carpeta", "Compartir {name}", "Añadir persona", "Correo electrónico", "Rol", "Lector",
    "Editor", "Añadir", "Personas con acceso", "Propietario", "Acceso general", "Restringido", "Cualquier persona con el enlace", "Solo las personas añadidas pueden abrir este elemento", "Cualquier persona con el enlace puede abrir este elemento", "Ajustes del enlace",
    "Solicitar contraseña", "Contraseña del enlace", "Al menos 8 caracteres", "Caduca el", "Cerrar las sesiones desbloqueadas existentes", "Guardar ajustes", "Copiar enlace", "Hecho", "Tema", "Idioma",
    "Tema oscuro", "Tema claro", "Ajustes de la interfaz", "Guardar", "Volver a los archivos"
  ], [
    "Iniciar sesión", "Iniciar sesión en {name}", "Nombre de usuario o correo", "Contraseña", "Continuar", "He olvidado mi nombre de usuario", "¿Has olvidado la contraseña?", "¿No tienes cuenta?", "Registrarse", "Crear una cuenta",
    "Nombre de usuario", "Repite la contraseña", "Confirma tu correo", "Código de verificación", "Iniciar sesión", "Reenviar código", "Cuenta", "Perfil", "Correo verificado", "Eliminar cuenta", "Tu cuenta se eliminará definitivamente después de 30 días"
  ]);

  add("sv", [
    "Mina filer", "Senaste", "Favoriter", "Lagring", "Villkor", "Integritet", "Inloggningsinställningar", "Logga ut", "Sök", "Skapa",
    "Ny mapp", "Ladda upp filer", "Namn", "Storlek", "Ändrad", "Mapp", "Öppna", "Dela", "Byt namn", "Radera",
    "Ladda ned", "Lägg till i favoriter", "Ta bort från favoriter", "Den här mappen är tom", "Ladda upp filer eller skapa en mapp", "Dela {name}", "Lägg till person", "E-post", "Roll", "Läsbehörighet",
    "Redigeringsbehörighet", "Lägg till", "Personer med åtkomst", "Ägare", "Allmän åtkomst", "Begränsad", "Alla med länken", "Endast tillagda personer kan öppna objektet", "Alla med länken kan öppna objektet", "Länkinställningar",
    "Kräv lösenord", "Länklösenord", "Minst 8 tecken", "Upphör", "Logga ut befintliga upplåsta sessioner", "Spara inställningar", "Kopiera länk", "Klar", "Tema", "Språk",
    "Mörkt tema", "Ljust tema", "Gränssnittsinställningar", "Spara", "Tillbaka till filer"
  ], [
    "Logga in", "Logga in på {name}", "Användarnamn eller e-post", "Lösenord", "Fortsätt", "Glömt användarnamn", "Glömt lösenordet?", "Inget konto?", "Registrera dig", "Skapa konto",
    "Användarnamn", "Upprepa lösenordet", "Bekräfta din e-post", "Verifieringskod", "Logga in", "Skicka koden igen", "Konto", "Profil", "Verifierad e-post", "Radera konto", "Ditt konto raderas permanent efter 30 dagar"
  ]);

  add("ar", [
    "ملفاتي", "الأخيرة", "المفضلة", "مساحة التخزين", "الشروط", "الخصوصية", "إعدادات تسجيل الدخول", "تسجيل الخروج", "بحث", "إنشاء",
    "مجلد جديد", "رفع ملفات", "الاسم", "الحجم", "تاريخ التعديل", "مجلد", "فتح", "مشاركة", "إعادة تسمية", "حذف",
    "تنزيل", "إضافة إلى المفضلة", "إزالة من المفضلة", "هذا المجلد فارغ", "ارفع ملفات أو أنشئ مجلدًا", "مشاركة {name}", "إضافة شخص", "البريد الإلكتروني", "الدور", "مشاهد",
    "محرر", "إضافة", "الأشخاص الذين لديهم صلاحية الوصول", "المالك", "الوصول العام", "مقيّد", "أي شخص لديه الرابط", "لا يمكن فتح هذا العنصر إلا للأشخاص الذين تمت إضافتهم", "يمكن لأي شخص لديه الرابط فتح هذا العنصر", "إعدادات الرابط",
    "طلب كلمة مرور", "كلمة مرور الرابط", "8 أحرف على الأقل", "تاريخ الانتهاء", "تسجيل خروج جلسات الفتح الحالية", "حفظ الإعدادات", "نسخ الرابط", "تم", "المظهر", "اللغة",
    "المظهر الداكن", "المظهر الفاتح", "إعدادات الواجهة", "حفظ", "العودة إلى الملفات"
  ], [
    "تسجيل الدخول", "تسجيل الدخول إلى {name}", "اسم المستخدم أو البريد الإلكتروني", "كلمة المرور", "متابعة", "نسيت اسم المستخدم", "هل نسيت كلمة المرور؟", "ليس لديك حساب؟", "التسجيل", "إنشاء حساب",
    "اسم المستخدم", "تكرار كلمة المرور", "تأكيد بريدك الإلكتروني", "رمز التحقق", "تسجيل الدخول", "إعادة إرسال الرمز", "الحساب", "الملف الشخصي", "بريد إلكتروني موثّق", "حذف الحساب", "سيُحذف حسابك نهائيًا بعد 30 يومًا"
  ]);

  add("ur", [
    "میری فائلیں", "حالیہ", "پسندیدہ", "اسٹوریج", "شرائط", "رازداری", "لاگ اِن کی ترتیبات", "لاگ آؤٹ", "تلاش", "بنائیں",
    "نیا فولڈر", "فائلیں اپ لوڈ کریں", "نام", "سائز", "ترمیم شدہ", "فولڈر", "کھولیں", "شیئر کریں", "نام تبدیل کریں", "حذف کریں",
    "ڈاؤن لوڈ", "پسندیدہ میں شامل کریں", "پسندیدہ سے ہٹائیں", "یہ فولڈر خالی ہے", "فائلیں اپ لوڈ کریں یا فولڈر بنائیں", "{name} شیئر کریں", "شخص شامل کریں", "ای میل", "کردار", "دیکھنے والا",
    "ترمیم کار", "شامل کریں", "رسائی رکھنے والے لوگ", "مالک", "عمومی رسائی", "محدود", "لنک رکھنے والا ہر شخص", "صرف شامل کیے گئے لوگ یہ آئٹم کھول سکتے ہیں", "لنک رکھنے والا ہر شخص یہ آئٹم کھول سکتا ہے", "لنک کی ترتیبات",
    "پاس ورڈ درکار ہے", "لنک کا پاس ورڈ", "کم از کم 8 حروف", "میعاد ختم ہونے کی تاریخ", "موجودہ کھلے سیشنز سے سائن آؤٹ کریں", "ترتیبات محفوظ کریں", "لنک کاپی کریں", "مکمل", "تھیم", "زبان",
    "گہری تھیم", "ہلکی تھیم", "انٹرفیس کی ترتیبات", "محفوظ کریں", "فائلوں پر واپس جائیں"
  ], [
    "لاگ اِن", "{name} میں لاگ اِن کریں", "صارف نام یا ای میل", "پاس ورڈ", "جاری رکھیں", "صارف نام بھول گئے", "پاس ورڈ بھول گئے؟", "اکاؤنٹ نہیں ہے؟", "رجسٹر کریں", "اکاؤنٹ بنائیں",
    "صارف نام", "پاس ورڈ دوبارہ درج کریں", "اپنی ای میل کی تصدیق کریں", "تصدیقی کوڈ", "سائن اِن", "کوڈ دوبارہ بھیجیں", "اکاؤنٹ", "پروفائل", "تصدیق شدہ ای میل", "اکاؤنٹ حذف کریں", "آپ کا اکاؤنٹ 30 دن بعد مستقل طور پر حذف کر دیا جائے گا"
  ]);

  add("hi", [
    "मेरी फ़ाइलें", "हाल की", "पसंदीदा", "स्टोरेज", "शर्तें", "गोपनीयता", "साइन-इन सेटिंग", "लॉग आउट", "खोजें", "बनाएँ",
    "नया फ़ोल्डर", "फ़ाइलें अपलोड करें", "नाम", "आकार", "बदलाव की तारीख", "फ़ोल्डर", "खोलें", "शेयर करें", "नाम बदलें", "मिटाएँ",
    "डाउनलोड करें", "पसंदीदा में जोड़ें", "पसंदीदा से हटाएँ", "यह फ़ोल्डर खाली है", "फ़ाइलें अपलोड करें या फ़ोल्डर बनाएँ", "{name} शेयर करें", "व्यक्ति जोड़ें", "ईमेल", "भूमिका", "देखने वाला",
    "संपादक", "जोड़ें", "ऐक्सेस वाले लोग", "मालिक", "सामान्य ऐक्सेस", "प्रतिबंधित", "लिंक वाला कोई भी व्यक्ति", "सिर्फ़ जोड़े गए लोग यह आइटम खोल सकते हैं", "लिंक वाला कोई भी व्यक्ति यह आइटम खोल सकता है", "लिंक की सेटिंग",
    "पासवर्ड ज़रूरी", "लिंक का पासवर्ड", "कम से कम 8 अक्षर", "समाप्ति", "मौजूदा अनलॉक सत्रों से साइन आउट करें", "सेटिंग सेव करें", "लिंक कॉपी करें", "हो गया", "थीम", "भाषा",
    "गहरी थीम", "हल्की थीम", "इंटरफ़ेस सेटिंग", "सेव करें", "फ़ाइलों पर वापस जाएँ"
  ], [
    "लॉग इन", "{name} में लॉग इन करें", "यूज़रनेम या ईमेल", "पासवर्ड", "जारी रखें", "यूज़रनेम भूल गए", "पासवर्ड भूल गए?", "खाता नहीं है?", "रजिस्टर करें", "खाता बनाएँ",
    "यूज़रनेम", "पासवर्ड दोबारा लिखें", "अपना ईमेल पक्का करें", "पुष्टि कोड", "साइन इन", "कोड फिर भेजें", "खाता", "प्रोफ़ाइल", "पुष्टि किया गया ईमेल", "खाता मिटाएँ", "आपका खाता 30 दिनों के बाद हमेशा के लिए मिटा दिया जाएगा"
  ]);

  const SOURCE_LOCALE = "ru";

  function normalizeLocale(value) {
    const locale = String(value || "").trim().toLowerCase().split(/[-_]/)[0];
    return Object.hasOwn(CATALOG, locale) ? locale : SOURCE_LOCALE;
  }

  function interpolate(message, variables = {}) {
    return message.replace(/\{([^{}]+)\}/g, (match, name) =>
      Object.hasOwn(variables, name) ? String(variables[name]) : match
    );
  }

  function createRuntime(locale) {
    const selected = CATALOG[locale] || CATALOG[SOURCE_LOCALE];
    return {
      locale,
      t(key, variables) {
        return interpolate(selected[key] ?? CATALOG[SOURCE_LOCALE][key] ?? key, variables);
      },
      translate(root = document) {
        root.querySelectorAll("[data-i18n]").forEach((element) => {
          const key = element.getAttribute("data-i18n");
          const variables = {};
          if (element.dataset.i18nName) variables.name = element.dataset.i18nName;
          element.textContent = this.t(key, variables);
        });
        root.querySelectorAll("[data-i18n-placeholder]").forEach((element) => {
          const key = element.getAttribute("data-i18n-placeholder");
          element.setAttribute("placeholder", this.t(key));
        });
      }
    };
  }

  function initialize() {
    const locale = normalizeLocale(document.documentElement.getAttribute("lang"));
    const runtime = createRuntime(locale);
    runtime.translate(document);
    window.CloudNimbusI18n = runtime;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();

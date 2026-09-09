import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "denis.yoink"
  ipcTarget: "denis.yoink"
  implicitWidth: icon.implicitWidth
  implicitHeight: icon.implicitHeight

  readonly property var downloadService: bar && bar.shell ? bar.shell.serviceFor("denis.yoink") : null
  readonly property bool workerRunning: downloadService ? downloadService.running : false
  readonly property bool bookWorkerRunning: downloadService ? downloadService.bookRunning : false
  readonly property bool operationRunning: root.workerRunning || root.bookWorkerRunning

  property bool configuring: false
  property bool video: false
  property bool games: false
  property bool books: false
  property var gameResults: []
  property var selectedGame: null
  property string gameStatus: "Browse trending games or search the catalogue."
  property var gameSources: []
  property bool gameSourcesLoading: false
  property var bookResults: []
  property var selectedBook: null
  property string bookStatus: "Search the Library Genesis catalogue."
  property string bookLanguage: "English"
  property bool bookHasNext: false
  readonly property bool bookPageLoading: root.books && root.selectedBook === null && root.bookWorkerRunning && root.downloadService && root.downloadService.bookAction === "book-search"
  onSelectedGameChanged: if (detailCoverImage) detailCoverImage.fallbackIndex = 0
  onSelectedBookChanged: if (bookDetailCoverImage) bookDetailCoverImage.fallbackIndex = 0
  Timer { id: gameSourcesTimer; interval: 0; repeat: false; onTriggered: if (root.selectedGame) root.gameTask("game-sources", {name: root.selectedGame.name}) }
  property int gamePage: 1
  property bool gameBrowsingTrending: true
  property int bookPage: 1
  property bool searching: false
  property var searchResults: []
  property var selectedSong: null
  readonly property bool musicInput: searching ? selectedSong !== null : spotifyLink
  readonly property bool inputReady: searching ? selectedSong !== null : link.text.trim() !== ""
  readonly property bool videoInputReady: videoLink.text.trim() !== "" && !spotifyVideoLink
  property string musicSource: "qobuz"
  property string musicCodec: "original"
  property int musicQuality: 3
  readonly property bool spotifyLink: link.text.indexOf("open.spotify.com") !== -1 || link.text.indexOf("spotify:") === 0
  property string mode: "Audio"
  property string videoFormat: "auto"
  property string audioFormat: "best"
  property string videoQuality: "Best"
  property string audioQuality: "0"
  property string status: "Paste a link or search for a song to get started."
  property string logText: ""
  property bool cancelling: false
  property string action: "download"
  readonly property bool spotifyVideoLink: videoLink.text.indexOf("open.spotify.com") !== -1 || videoLink.text.indexOf("spotify:") === 0

  function sourceLabel(url) {
    const name = String(url || "").replace(/^https?:\/\//, "").replace(/^www\./, "").split("/")[0].split(".")[0]
    return name.replace(/[-_]+/g, " ").replace(/\b\w/g, function(letter) { return letter.toUpperCase() })
  }

  function bookDownloadLabel() {
    const extension = String(root.selectedBook && root.selectedBook.extension || "").replace(/^\./, "").toUpperCase()
    return extension ? "Download " + extension : "Download"
  }

  function appendLog(line) {
    if (line.indexOf("CONFIG:") === 0) {
      try { configForm.apply(JSON.parse(line.slice(7))) } catch (e) {}
      return
    }
    if (line.indexOf("SEARCH:") === 0) {
      try { root.searchResults = JSON.parse(line.slice(7)) } catch (e) { root.status = "Could not read search results." }
      return
    }
    if (line.indexOf("GAMES:") === 0) {
      try { root.gameResults = JSON.parse(line.slice(6)); root.gameStatus = root.gameResults.length ? "Select a game to view details." : "No games found." } catch (e) { root.gameStatus = "Could not read game results." }
      return
    }
    if (line.indexOf("GAME_DETAIL:") === 0) {
      try { root.selectedGame = JSON.parse(line.slice(12)); root.gameStatus = "Game details loaded." } catch (e) { root.gameStatus = "Could not read game details." }
      return
    }
    if (line.indexOf("GAME_SOURCES:") === 0) {
      try { root.gameSources = JSON.parse(line.slice(13)); root.gameSourcesLoading = false; root.gameStatus = root.gameSources.length ? "Matching game websites found." : "No configured website matched this title." } catch (e) { root.gameSources = []; root.gameSourcesLoading = false }
      return
    }
    if (line.indexOf("BOOKS:") === 0) {
      try {
        const payload = JSON.parse(line.slice(6))
        root.bookResults = Array.isArray(payload) ? payload : (Array.isArray(payload.items) ? payload.items : [])
        root.bookHasNext = Array.isArray(payload) ? root.bookResults.length >= 18 : !!payload.has_next
        root.bookStatus = root.bookResults.length ? "Select a book to view details." : "No books found."
      } catch (e) {
        root.bookResults = []
        root.bookHasNext = false
        root.bookStatus = "Could not read book results."
      }
      return
    }
    if (line.indexOf("BOOK_DETAIL:") === 0) {
      try {
        const previous = root.selectedBook || {}
        const details = JSON.parse(line.slice(12))
        for (const field of ["cover", "language", "pages", "size", "extension", "md5"]) {
          if (!details[field] && previous[field]) details[field] = previous[field]
        }
        if ((!details.coverFallbacks || details.coverFallbacks.length === 0) && previous.cover && details.cover && details.cover !== previous.cover) details.coverFallbacks = [previous.cover]
        root.selectedBook = details
        root.bookStatus = "Book details loaded."
      } catch (e) { root.bookStatus = "Could not read book details." }
      return
    }
    if (line.indexOf("BOOK_ERROR:") === 0) {
      root.bookHasNext = false
      root.bookStatus = line.slice(11) || "Book catalogue unavailable."
      return
    }
    if (line.indexOf("BOOK_DOWNLOAD:") === 0) {
      try {
        const result = JSON.parse(line.slice(14))
        root.bookStatus = result.path ? "Book downloaded to " + result.path : "Book downloaded."
      } catch (e) { root.bookStatus = "Book downloaded." }
      return
    }
    if (line.indexOf("BOOK_DOWNLOAD_ERROR:") === 0) {
      root.bookStatus = line.slice(20) || "Book download failed."
      return
    }
    if (line.indexOf("OPEN:") === 0) {
      const url = line.slice(5)
      if (url.indexOf("https://accounts.spotify.com/") === 0) {
        Quickshell.execDetached(["omarchy-launch-browser", url])
        root.status = "Finish connecting Spotify in your browser."
      }
      return
    }
    logText = (logText + line + "\n").slice(-16000)
    if (line.indexOf("[download]") === 0) status = line
  }

  function clearDownload() {
    if (root.operationRunning) return
    link.text = ""
    videoLink.text = ""
    query.text = ""
    searchResults = []
    selectedSong = null
    gameResults = []
    selectedGame = null
    bookResults = []
    selectedBook = null
    gamePage = 1
    gameBrowsingTrending = true
    bookPage = 1
    bookHasNext = false
    bookLanguage = "English"
    gameSources = []
    gameSourcesLoading = false
    logText = ""
    status = "Paste a link or search for a song to get started."
    cancelling = false
    configuring = false
    video = false
    games = false
    books = false
    if (root.downloadService) root.downloadService.clearResult()
    scroll.contentY = 0
    if (searching) query.forceActiveFocus(); else link.forceActiveFocus()
  }

  function start(action) {
    if (root.workerRunning) return
    root.action = action
    root.cancelling = false
    root.logText = ""
    root.status = "Starting download…"
    const sourceLink = root.video ? videoLink.text : link.text
    const outputPath = root.video ? videoDestination.text : destination.text
    const options = {url: sourceLink, mode: mode, action: action,
      format: mode === "Video" ? videoFormat : audioFormat,
      quality: mode === "Video" ? videoQuality : audioQuality,
      output: outputPath,
      selection: searching ? selectedSong : null, source: musicSource, musicCodec: musicCodec, musicQuality: musicQuality}
    runTask(action, options)
  }

  function gameTask(action, options) {
    if (root.workerRunning || !root.downloadService) return
    root.gameStatus = action === "game-search" ? "Searching games…" : action === "game-sources" ? "Checking game websites…" : "Loading game catalogue…"
    root.runTask(action, options)
  }

  function bookTask(action, options) {
    if (root.bookWorkerRunning || !root.downloadService) return
    root.bookStatus = action === "book-search" ? "Searching books…" : action === "book-download" ? "Preparing book download…" : "Loading book details…"
    root.runTask(action, options)
  }

  function reloadBooks() {
    root.selectedBook = null
    root.bookPage = 1
    root.bookHasNext = false
    if (!bookQuery.text.trim()) {
      root.bookResults = []
      root.bookStatus = "Enter a title or author to search."
      return
    }
    root.bookTask("book-search", {query: bookQuery.text, page: 1, language: root.bookLanguage})
  }

  function beginGameSearch(value) {
    const text = String(value || "").trim()
    if (!text) return
    root.selectedGame = null
    root.gameSources = []
    root.gameSourcesLoading = false
    root.gamePage = 1
    root.gameBrowsingTrending = false
    root.gameTask("game-search", {query: text})
  }

  function beginBookSearch(value) {
    const text = String(value || "").trim()
    if (!text) return
    root.selectedBook = null
    root.bookResults = []
    root.bookPage = 1
    root.bookHasNext = false
    root.bookTask("book-search", {query: text, page: 1, language: root.bookLanguage})
  }

  function runTask(action, options) {
    if (!root.downloadService) return
    if (action.indexOf("book-") === 0) {
      root.logText = ""
      root.downloadService.runTask(action, options)
      return
    }
    if (root.workerRunning) return
    root.action = action
    root.cancelling = false
    if (action !== "config-load") root.logText = ""
    root.status = action === "config-load" ? root.status : "Working…"
    root.downloadService.runTask(action, options)
  }

  function workerExited(code, completedAction, wasCancelled) {
      if (completedAction.indexOf("book-") === 0) {
        if (wasCancelled) root.bookStatus = "Cancelled."
        return
      }
      if (completedAction === "config-load" && code === 0) return
      if (completedAction === "game-detail" && root.selectedGame) {
        root.gameSourcesLoading = true
        gameSourcesTimer.restart()
      }
      root.status = wasCancelled ? "Cancelled."
        : code === 2 ? "Some tracks could not be completed. See the report below."
        : code !== 0 ? (completedAction.indexOf("book-") === 0 ? root.bookStatus : "Failed — see details below.")
        : completedAction === "search" ? (root.searchResults.length ? "Select a song below." : "No songs found. Try adding the artist name.")
      : completedAction === "download" ? "Download complete." : completedAction.indexOf("game-") === 0 ? root.gameStatus : completedAction.indexOf("book-") === 0 ? root.bookStatus : "Configuration updated."
  }

  Connections {
    target: root.downloadService
    function onOutputLine(line) { root.appendLog(line) }
    function onFinished(code, completedAction, wasCancelled) { root.workerExited(code, completedAction, wasCancelled) }
    function onConfigDataChanged() {
      if (root.downloadService && root.downloadService.configData) configForm.apply(root.downloadService.configData)
    }
    function onSearchResultsChanged() {
      if (root.downloadService) root.searchResults = root.downloadService.searchResults
    }
  }

  onDownloadServiceChanged: {
    if (!root.downloadService) return
    if (root.downloadService.configData) configForm.apply(root.downloadService.configData)
    root.searchResults = root.downloadService.searchResults
  }

  BarIconButton {
    id: icon
    anchors.fill: parent
    bar: root.bar
    text: "\uf019"
    slotSize: Style.bar.statusSlot
    fontSize: Style.font.caption
    foreground: root.downloadService && root.downloadService.resultState === "success" ? Color.accent
      : root.downloadService && root.downloadService.resultState === "failed" ? Color.urgent
      : root.bar ? root.bar.barForeground : Color.foreground
    tooltipText: root.workerRunning ? root.status : "Yoink"
    onPressed: root.toggle()
  }

  Rectangle {
    id: progressBadge
    z: 3
    visible: root.downloadService && root.downloadService.progressTotal > 0
    anchors.right: parent.right
    anchors.top: parent.top
    width: Math.max(height, badgeText.implicitWidth + Style.space(4))
    height: Math.max(10, Style.font.bodySmall + Style.space(2))
    radius: height / 2
    color: root.downloadService && root.downloadService.resultState === "failed" ? Color.urgent
      : root.downloadService && root.downloadService.resultState === "success" ? Color.accent
      : Color.bar.background
    border.width: 1
    border.color: root.bar ? root.bar.barForeground : Color.foreground
    Text {
      id: badgeText
      anchors.centerIn: parent
      text: root.downloadService ? root.downloadService.progressPercent + "%" : ""
      color: root.downloadService && root.downloadService.resultState === "failed" ? Color.background
        : root.downloadService && root.downloadService.resultState === "success" ? Color.background
        : root.bar ? root.bar.barForeground : Color.foreground
      font.family: Style.font.family
      font.pixelSize: Math.max(7, Style.font.bodySmall * 0.72)
      font.bold: true
    }
  }

  component Label: Text {
    color: Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    textFormat: Text.PlainText
    wrapMode: Text.Wrap
  }

  component Choice: Button {
    focusable: true
    bordered: true
    enabled: !root.workerRunning
  }

  KeyboardPanel {
    id: popup
    anchorItem: icon
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: root.configuring ? configForm : root.games ? gameQuery : root.books ? bookQuery : root.video ? videoLink : link
    contentWidth: fittedContentWidth(Style.space(620))
    contentHeight: fittedContentHeight(form.implicitHeight)

    Item {
      anchors.fill: parent
      Keys.onEscapePressed: root.close()

      Flickable {
        id: scroll
        anchors.fill: parent
        clip: true
        contentHeight: form.implicitHeight
        contentWidth: width
        boundsBehavior: Flickable.StopAtBounds

        Column {
          id: form
          width: scroll.width
          spacing: Style.space(12)

          Row {
            width: parent.width
            Label { text: "Yoink"; font.pixelSize: Style.font.title; width: parent.width - clearButton.width - closeButton.width }
            Button {
              id: clearButton
              text: "Clear"
              tooltipText: "Clear the link and progress log"
              enabled: !root.operationRunning
              focusable: true
              onClicked: root.clearDownload()
            }
            Button { id: closeButton; text: "✕"; focusable: true; onClicked: root.close() }
          }
          Row {
            width: parent.width; spacing: Style.space(6)
            Button { id: musicTab; text: "Music"; selected: !root.configuring && !root.video && !root.games && !root.books; focusable: true; onClicked: { root.video = false; root.games = false; root.books = false; root.configuring = false; root.mode = "Audio" } }
            Button { id: videoTab; text: "Video"; selected: !root.configuring && root.video; focusable: true; onClicked: { root.video = true; root.games = false; root.books = false; root.configuring = false; root.searching = false; root.selectedSong = null; root.mode = "Video" } }
            Button { id: gamesTab; text: "Games"; selected: root.games; focusable: true; onClicked: { root.video = false; root.games = true; root.books = false; root.configuring = false; root.selectedGame = null; root.gameTask("game-trending", {}) } }
            Button { id: booksTab; text: "Books"; selected: root.books; focusable: true; onClicked: { root.video = false; root.games = false; root.books = true; root.configuring = false; root.selectedBook = null; root.bookResults = []; root.bookPage = 1; root.bookStatus = "Enter a title or author to search." } }
            Item { width: Math.max(0, parent.width - musicTab.width - videoTab.width - gamesTab.width - booksTab.width - settingsTab.width - Style.space(30)); height: 1 }
            Button { id: settingsTab; text: "Settings"; selected: root.configuring; focusable: true; onClicked: { root.video = false; root.games = false; root.books = false; root.configuring = true } }
          }
          Configuration {
            id: configForm
            width: parent.width
            visible: root.configuring && !root.games && !root.books
            busy: root.workerRunning
            onRequested: (action, payload) => root.runTask(action, payload)
          }
          Column {
            id: booksView
            visible: root.books && !root.configuring
            width: parent.width
            spacing: Style.space(10)
            TextField {
              id: bookQuery
              width: parent.width
              placeholderText: "Search books by title or author…"
              // The catalogue has its own worker, so the query remains
              // editable while a previous page is being fetched.
              enabled: true
              selectByMouse: true
              onAccepted: root.beginBookSearch(text)
            }
              Flow {
              width: parent.width; spacing: Style.space(6)
              Choice { text: "Search"; enabled: !root.bookWorkerRunning && bookQuery.text.trim() !== ""; onClicked: root.beginBookSearch(bookQuery.text) }
            }
            Column {
              width: parent.width; spacing: Style.space(6)
              Label { text: "Language"; font.pixelSize: Style.font.body }
              Flow {
                width: parent.width; spacing: Style.space(6)
                Repeater {
                  model: ["All", "English", "German", "French", "Spanish", "Italian", "Japanese", "Chinese"]
                  Choice {
                    required property string modelData
                    text: modelData
                    selected: root.bookLanguage === modelData
                    enabled: !root.bookWorkerRunning
                    onClicked: { root.bookLanguage = modelData; root.reloadBooks() }
                  }
                }
              }
            }
            Item {
              id: bookPagination
              visible: root.selectedBook === null
              width: parent.width
              height: Math.max(bookPageLabel.implicitHeight, bookLoadingLabel.implicitHeight, bookNavigation.implicitHeight)
              Label { id: bookPageLabel; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; text: "Page " + root.bookPage; leftPadding: Style.spacing.controlPaddingX; rightPadding: Style.spacing.controlPaddingX; topPadding: Style.spacing.controlPaddingY; bottomPadding: Style.spacing.controlPaddingY }
              Label { id: bookLoadingLabel; anchors.horizontalCenter: parent.horizontalCenter; anchors.verticalCenter: parent.verticalCenter; visible: root.bookPageLoading; text: "Loading..."; color: Color.accent; font.pixelSize: Style.font.body; leftPadding: Style.spacing.controlPaddingX; rightPadding: Style.spacing.controlPaddingX; topPadding: Style.spacing.controlPaddingY; bottomPadding: Style.spacing.controlPaddingY }
              Row {
                id: bookNavigation
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(6)
                Choice { id: previousBookPage; width: implicitWidth; opacity: root.bookPage > 1 ? 1 : 0; text: "‹ Previous"; enabled: !root.bookWorkerRunning && root.bookPage > 1; onClicked: { root.bookPage -= 1; root.bookTask("book-search", {query: bookQuery.text, page: root.bookPage, language: root.bookLanguage}) } }
                Choice { id: nextBookPage; width: implicitWidth; text: "Next ›"; visible: root.bookHasNext; enabled: !root.bookWorkerRunning && root.bookHasNext; onClicked: { root.bookPage += 1; root.bookTask("book-search", {query: bookQuery.text, page: root.bookPage, language: root.bookLanguage}) } }
              }
            }
            Column {
              id: bookList
              visible: root.selectedBook === null
              width: parent.width
              spacing: Style.space(6)
              Repeater {
                model: root.bookResults
                Rectangle {
                  required property var modelData
                  width: bookList.width
                  height: Style.space(78)
                  color: Color.background
                  border.color: bookMouse.containsMouse ? Color.accent : Color.foreground
                  border.width: 1
                  property int coverFallbackIndex: 0
                  onModelDataChanged: coverFallbackIndex = 0
                  Image {
                    id: bookCoverImage
                    anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom
                    anchors.margins: 1
                    width: Style.space(52)
                    fillMode: Image.PreserveAspectFit
                    source: modelData.cover || ""
                    visible: status === Image.Ready
                    asynchronous: true
                    onStatusChanged: {
                      if (status !== Image.Error) return
                      const fallbacks = modelData.coverFallbacks || []
                      if (parent.coverFallbackIndex < fallbacks.length) {
                        source = fallbacks[parent.coverFallbackIndex]
                        parent.coverFallbackIndex += 1
                      }
                    }
                  }
                  Label {
                    anchors.left: bookCoverImage.left; anchors.right: bookCoverImage.right
                    anchors.verticalCenter: parent.verticalCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: "No cover"
                    visible: bookCoverImage.status !== Image.Ready
                    font.pixelSize: Style.font.bodySmall
                    color: bookMouse.containsMouse ? Color.background : Color.foreground
                  }
                  Column {
                    anchors.left: bookCoverImage.right; anchors.leftMargin: Style.space(10)
                    anchors.right: parent.right; anchors.rightMargin: Style.space(10)
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Style.space(2)
                    Label { width: parent.width; text: modelData.name; font.pixelSize: Style.font.body; elide: Text.ElideRight; maximumLineCount: 1 }
                    Label { width: parent.width; text: modelData.author + (modelData.year ? " · " + modelData.year : ""); font.pixelSize: Style.font.bodySmall; elide: Text.ElideRight; maximumLineCount: 1 }
                    Label { width: parent.width; text: [modelData.language, modelData.extension, modelData.size].filter(function(value) { return value }).join(" · "); font.pixelSize: Style.font.bodySmall; elide: Text.ElideRight; maximumLineCount: 1 }
                  }
                  MouseArea { id: bookMouse; anchors.fill: parent; hoverEnabled: true; onClicked: { root.selectedBook = modelData; root.bookTask("book-detail", {id: modelData.id}) } }
                }
              }
            }
            Column {
              visible: root.selectedBook !== null
              width: parent.width; spacing: Style.space(8)
              Button { text: "← Back to books"; enabled: !root.bookWorkerRunning; focusable: true; onClicked: root.selectedBook = null }
              Image {
                id: bookDetailCoverImage
                property int fallbackIndex: 0
                width: parent.width; height: Style.space(270)
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                source: root.selectedBook ? (root.selectedBook.cover || "") : ""
                visible: status === Image.Ready
                onStatusChanged: {
                  if (status !== Image.Error || !root.selectedBook) return
                  const fallbacks = root.selectedBook.coverFallbacks || []
                  if (fallbackIndex < fallbacks.length) {
                    source = fallbacks[fallbackIndex]
                    fallbackIndex += 1
                  }
                }
              }
              Label { visible: bookDetailCoverImage.status !== Image.Ready; text: root.selectedBook ? root.selectedBook.name : ""; width: parent.width; horizontalAlignment: Text.AlignHCenter; font.pixelSize: Style.font.bodySmall }
              Label { text: root.selectedBook ? root.selectedBook.name : ""; font.pixelSize: Style.font.subtitle }
              Label { text: root.selectedBook ? "By " + root.selectedBook.author : ""; width: parent.width; font.pixelSize: Style.font.bodySmall }
              Label { text: root.selectedBook ? root.selectedBook.summary : ""; width: parent.width; font.pixelSize: Style.font.bodySmall; wrapMode: Text.Wrap }
              Flow {
                spacing: Style.space(6)
                Choice { text: "Open LibGen"; enabled: root.selectedBook && root.selectedBook.url !== ""; onClicked: if (root.selectedBook) Quickshell.execDetached(["omarchy-launch-browser", root.selectedBook.url]) }
                Choice {
                  text: root.bookDownloadLabel()
                  enabled: !root.bookWorkerRunning && root.selectedBook && root.selectedBook.name !== ""
                  onClicked: if (root.selectedBook) root.bookTask("book-download", {book: root.selectedBook})
                }
              }
            }
          }
          Column {
            id: gamesView
            visible: root.games && !root.configuring
            width: parent.width
            spacing: Style.space(10)
            TextField {
              id: gameQuery
              width: parent.width
              placeholderText: "Search games…"
              enabled: !root.workerRunning
              selectByMouse: true
              onAccepted: root.beginGameSearch(text)
            }
            Flow {
              width: parent.width; spacing: Style.space(6)
              Choice { text: "Search"; enabled: !root.workerRunning && gameQuery.text.trim() !== ""; onClicked: root.beginGameSearch(gameQuery.text) }
              Choice { text: "Trending"; enabled: !root.workerRunning; onClicked: { root.gamePage = 1; root.gameBrowsingTrending = true; root.gameTask("game-trending", {page: 1}) } }
            }
            Item {
              id: gamePagination
              visible: root.selectedGame === null && root.gameBrowsingTrending
              width: parent.width
              height: Math.max(pageLabel.implicitHeight, gameNavigation.implicitHeight)
              Label { id: pageLabel; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; text: "Page " + root.gamePage; leftPadding: Style.spacing.controlPaddingX; rightPadding: Style.spacing.controlPaddingX; topPadding: Style.spacing.controlPaddingY; bottomPadding: Style.spacing.controlPaddingY }
              Row {
                id: gameNavigation
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(6)
                Choice { id: previousPage; width: implicitWidth; opacity: root.gamePage > 1 ? 1 : 0; text: "‹ Previous"; color: hot ? Style.hoverFillFor(foreground, accent) : "transparent"; enabled: !root.workerRunning && root.gamePage > 1; onClicked: { root.gamePage -= 1; root.gameTask("game-trending", {page: root.gamePage}) } }
                Choice { id: nextPage; width: implicitWidth; opacity: root.gamePage < 5 ? 1 : 0; text: "Next ›"; color: hot ? Style.hoverFillFor(foreground, accent) : "transparent"; enabled: !root.workerRunning && root.gamePage < 5 && root.gameResults.length > 0; onClicked: { root.gamePage += 1; root.gameTask("game-trending", {page: root.gamePage}) } }
              }
            }
            Grid {
              visible: root.selectedGame === null
              width: parent.width
              columns: 3
              columnSpacing: Style.space(8); rowSpacing: Style.space(8)
              Repeater {
                model: root.gameResults
                Rectangle {
                  required property var modelData
                  width: (gamesView.width - Style.space(24)) / 3
                  height: width * 430 / 920
                  radius: 0
                  color: Color.background
                  border.color: cardMouse.containsMouse ? Color.accent : Color.foreground
                  border.width: 1
                  property int coverFallbackIndex: 0
                  Image {
                    id: coverImage; anchors.fill: parent; anchors.margins: 1; fillMode: Image.PreserveAspectFit
                    source: modelData.gridCover || ""; visible: status === Image.Ready; asynchronous: true
                    onStatusChanged: {
                      if (status !== Image.Error) return
                      const fallbacks = modelData.gridFallbacks || []
                      if (parent.coverFallbackIndex < fallbacks.length) {
                        source = fallbacks[parent.coverFallbackIndex]
                        parent.coverFallbackIndex += 1
                      }
                    }
                  }
                  Label {
                    anchors.centerIn: parent
                    width: parent.width - Style.space(12)
                    horizontalAlignment: Text.AlignHCenter
                    text: modelData.name
                    visible: coverImage.status !== Image.Ready
                    font.pixelSize: Style.font.bodySmall
                    color: cardMouse.containsMouse ? Color.background : Color.foreground
                  }
                  MouseArea { id: cardMouse; anchors.fill: parent; hoverEnabled: true; onClicked: { root.selectedGame = modelData; root.gameTask("game-detail", {id: modelData.id, source: modelData.source}) } }
                }
              }
            }
            Column {
              visible: root.selectedGame !== null
              width: parent.width; spacing: Style.space(8)
              Button { text: "← Back to games"; focusable: true; onClicked: root.selectedGame = null }
              Image {
                id: detailCoverImage
                property int fallbackIndex: 0
                width: parent.width; height: Style.space(270); fillMode: Image.PreserveAspectFit; asynchronous: true
                source: root.selectedGame ? (root.selectedGame.detailCover || root.selectedGame.gridCover || "") : ""
                visible: status === Image.Ready
                onStatusChanged: {
                  if (status !== Image.Error || !root.selectedGame) return
                  const fallbacks = root.selectedGame.detailFallbacks || []
                  if (fallbackIndex < fallbacks.length) {
                    source = fallbacks[fallbackIndex]
                    fallbackIndex += 1
                  }
                }
              }
              Label { text: root.selectedGame ? root.selectedGame.name : ""; font.pixelSize: Style.font.subtitle }
              Label { text: root.selectedGame ? root.selectedGame.summary : ""; width: parent.width; font.pixelSize: Style.font.bodySmall }
              Label { text: root.selectedGame ? ((root.selectedGame.genres || []).join(" · ") + (root.selectedGame.rating ? "\nRating " + root.selectedGame.rating + "/100" : "")) : ""; font.pixelSize: Style.font.bodySmall }
              Flow {
                spacing: Style.space(6)
                Repeater {
                  model: root.gameSources
                  Choice { required property var modelData; text: "Open " + root.sourceLabel(modelData.base); onClicked: Quickshell.execDetached(["omarchy-launch-browser", modelData.url]) }
                }
                Choice { text: "Open Steam"; onClicked: if (root.selectedGame) Quickshell.execDetached(["omarchy-launch-browser", "https://store.steampowered.com/app/" + root.selectedGame.id]) }
              }
              Label { visible: root.gameSourcesLoading; text: "Checking configured game websites…"; font.pixelSize: Style.font.bodySmall }
            }
          }
          Column {
            width: parent.width
            spacing: Style.space(12)
            visible: !root.configuring && !root.video && !root.games && !root.books
          Flow {
            width: parent.width; spacing: Style.space(6)
            Choice { text: "Paste link"; selected: !root.searching; onClicked: root.searching = false }
            Choice { text: "Search titles"; selected: root.searching; onClicked: { root.searching = true; query.forceActiveFocus() } }
          }
          Label {
            visible: !root.searching && /spotify.*[/:]artist[/:]/.test(link.text)
            width: parent.width
            text: "Artist links include albums and singles; repeated track IDs are skipped."
            font.pixelSize: Style.font.bodySmall
          }
          Column {
            visible: root.searching
            width: parent.width
            spacing: Style.space(8)
            Label { text: "Find a song · YouTube Music catalog" }
            TextField {
              id: query
              width: parent.width
              placeholderText: "Song title or artist and title…"
              enabled: !root.workerRunning
              selectByMouse: true
              onTextEdited: { root.selectedSong = null; root.searchResults = [] }
              onAccepted: if (!root.workerRunning && text.trim()) root.runTask("search", {query: text})
            }
            Choice {
              text: "Search"
              enabled: !root.workerRunning && query.text.trim() !== ""
              onClicked: { root.selectedSong = null; root.searchResults = []; root.runTask("search", {query: query.text}) }
            }
            Flickable {
              visible: root.searchResults.length > 0
              width: parent.width
              height: Math.min(resultsColumn.implicitHeight, Style.space(220))
              contentWidth: width
              contentHeight: resultsColumn.implicitHeight
              clip: true
              Column {
                id: resultsColumn
                width: parent.width
                spacing: Style.space(4)
                Repeater {
                  model: root.searchResults
                  Button {
                    required property var modelData
                    width: parent.width
                    height: resultLabel.implicitHeight + Style.space(16)
                    Label {
                      id: resultLabel
                      anchors.left: parent.left
                      anchors.leftMargin: Style.space(10)
                      anchors.verticalCenter: parent.verticalCenter
                      width: parent.width - Style.space(20)
                      text: modelData.title + "\n" + modelData.artists.join(", ") + " · " + modelData.durationLabel + (modelData.album ? "\n" + modelData.album : "")
                    }
                    selected: root.selectedSong !== null && root.selectedSong.videoId === modelData.videoId
                    enabled: !root.workerRunning
                    leftAlign: true
                    focusable: true
                    bordered: true
                    onClicked: root.selectedSong = modelData
                  }
                }
              }
            }
            Label {
              visible: root.selectedSong !== null
              width: parent.width
              text: root.selectedSong ? "Selected: " + root.selectedSong.title + " — " + root.selectedSong.artists.join(", ") : ""
            }
          }
          TextField {
            id: link
            visible: !root.searching
            width: parent.width
            placeholderText: "Paste a Spotify or YouTube link…"
            enabled: !root.workerRunning
            selectByMouse: true
          }
          Label { visible: !root.searching && !root.spotifyLink; text: "Audio Quality" }
          Flow {
            width: parent.width; spacing: Style.space(6)
            Repeater {
              model: root.searching || root.spotifyLink ? [] : ["0", "192K", "256K", "320K"]
              Choice {
                required property string modelData
                text: modelData === "0" ? "Best" : modelData
                selected: modelData === root.audioQuality
                onClicked: root.audioQuality = modelData
              }
            }
          }
          Label { visible: !root.searching && !root.spotifyLink; text: "Audio Format" }
          Flow {
            width: parent.width; spacing: Style.space(6)
            Repeater {
              model: root.searching || root.spotifyLink ? [] : ["best", "mp3", "m4a", "opus", "flac", "wav"]
              Choice {
                required property string modelData
                text: modelData === "best" ? "Original" : modelData.toUpperCase()
                selected: modelData === root.audioFormat
                onClicked: root.audioFormat = modelData
              }
            }
          }
          Flow {
            width: parent.width; spacing: Style.space(6)
            visible: !root.searching && !root.spotifyLink
          }
          Column {
            visible: root.musicInput
            width: parent.width
            spacing: Style.space(10)
            Label { text: "Preferred Source" }
            Flow {
              width: parent.width; spacing: Style.space(6)
              Repeater {
                model: ["qobuz", "deezer", "tidal"]
                Choice {
                  required property string modelData
                  text: modelData.charAt(0).toUpperCase() + modelData.slice(1)
                  selected: root.musicSource === modelData
                  onClicked: root.musicSource = modelData
                }
              }
            }
            Label {
              width: parent.width
              text: "Yoink tries this service first, then your other configured services. YouTube Music is always the last resort."
              font.pixelSize: Style.font.bodySmall
            }
            Label { text: "Quality · limited by source and account" }
            Flow {
              width: parent.width; spacing: Style.space(6)
              Repeater {
                model: ["Lossy", "CD", "Hi-res", "Maximum"]
                Choice { required property string modelData; required property int index; text: modelData; selected: root.musicQuality === index + 1; onClicked: root.musicQuality = index + 1 }
              }
            }
            Label { text: "Output Format" }
            Flow {
              width: parent.width; spacing: Style.space(6)
              Repeater {
                model: ["original", "flac", "mp3", "opus"]
                Choice { required property string modelData; text: modelData.toUpperCase(); selected: root.musicCodec === modelData; onClicked: root.musicCodec = modelData }
              }
            }
          }
          Label { text: "Save To" }
          TextField {
            id: destination
            width: parent.width
            placeholderText: root.searching || root.musicInput ? "~/Downloads/Yoink/Music" : "~/Downloads/Yoink/Audio"
            enabled: !root.workerRunning
            selectByMouse: true
          }
          Flow {
            width: parent.width; spacing: Style.space(6)
            Choice { text: root.searching || root.musicInput ? "Download Music" : "Download Audio"; enabled: !root.workerRunning && root.inputReady; onClicked: root.start("download") }
          }
          }
          Column {
            id: videoView
            visible: root.video && !root.configuring && !root.games
            width: parent.width
            spacing: Style.space(10)
            TextField {
              id: videoLink
              width: parent.width
              placeholderText: "Paste a YouTube link…"
              enabled: !root.workerRunning
              selectByMouse: true
            }
            Label {
              visible: root.spotifyVideoLink
              width: parent.width
              text: "Video downloads require a YouTube link. Use Music for Spotify or audio downloads."
              font.pixelSize: Style.font.bodySmall
            }
            Label { text: "Video Quality" }
            Flow {
              width: parent.width; spacing: Style.space(6)
              Repeater {
                model: ["Best", "2160", "1440", "1080", "720", "480"]
                Choice {
                  required property string modelData
                  text: modelData
                  selected: root.videoQuality === modelData
                  onClicked: root.videoQuality = modelData
                }
              }
            }
            Label { text: "Video Format" }
            Flow {
              width: parent.width; spacing: Style.space(6)
              Repeater {
                model: ["auto", "mkv", "mp4"]
                Choice {
                  required property string modelData
                  text: modelData.toUpperCase()
                  selected: root.videoFormat === modelData
                  onClicked: root.videoFormat = modelData
                }
              }
            }
            Label { text: "Save To" }
            TextField {
              id: videoDestination
              width: parent.width
              placeholderText: "~/Downloads/Yoink/Video"
              enabled: !root.workerRunning
              selectByMouse: true
            }
            Flow {
              width: parent.width; spacing: Style.space(6)
              Choice { text: "Download Video"; enabled: !root.workerRunning && root.videoInputReady; onClicked: root.start("download") }
            }
          }
          Button {
            visible: root.operationRunning
            text: root.downloadService && root.downloadService.cancelPending ? "Stopping…" : "Cancel"
            focusable: true
            enabled: root.downloadService && !root.downloadService.cancelPending
            onClicked: if (root.downloadService) root.downloadService.cancel()
          }
          Label {
            visible: root.workerRunning && root.downloadService && root.downloadService.progressTotal > 0
            width: parent.width
            text: root.downloadService ? "Download Progress: " + root.downloadService.progressPercent + "%" : ""
            font.pixelSize: Style.font.bodySmall
          }
          Label {
            visible: !root.bookPageLoading
            width: parent.width
            text: root.books ? root.bookStatus : root.games ? root.gameStatus : root.status
          }
          Label { visible: root.operationRunning; width: parent.width; text: "You can close this popup while the operation continues."; font.pixelSize: Style.font.bodySmall }
          Flickable {
            visible: root.logText !== ""
            width: parent.width
            height: visible ? Style.space(140) : 0
            clip: true
            contentWidth: width
            contentHeight: details.implicitHeight
            onContentHeightChanged: contentY = Math.max(0, contentHeight - height)
            TextEdit {
              id: details
              width: parent.width
              text: root.logText
              readOnly: true
              selectByMouse: true
              wrapMode: TextEdit.Wrap
              textFormat: TextEdit.PlainText
              color: Color.foreground
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
            }
          }
        }
      }
    }
  }
}

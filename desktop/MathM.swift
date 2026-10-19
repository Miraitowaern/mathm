import Cocoa
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var backend: Process?
    var timer: Timer?
    var readyFile: URL!
    var started = Date()
    var currentPort: Int = 0
    var quitting = false
    let fm = FileManager.default
    var support: URL { fm.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/MathM", isDirectory: true) }

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMenu()
        let config = WKWebViewConfiguration()
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self; webView.uiDelegate = self
        window = NSWindow(contentRect: NSRect(x:0,y:0,width:1280,height:850), styleMask:[.titled,.closable,.miniaturizable,.resizable], backing:.buffered, defer:false)
        window.title = "MathM · 数模研究工作台"
        window.minSize = NSSize(width:820,height:620)
        let container=NSView(frame:NSRect(x:0,y:0,width:1280,height:850))
        webView.translatesAutoresizingMaskIntoConstraints=false
        container.addSubview(webView)
        NSLayoutConstraint.activate([webView.leadingAnchor.constraint(equalTo:container.leadingAnchor),webView.trailingAnchor.constraint(equalTo:container.trailingAnchor),webView.topAnchor.constraint(equalTo:container.topAnchor),webView.bottomAnchor.constraint(equalTo:container.bottomAnchor)])
        window.contentView = container; window.center(); window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        webView.loadHTMLString("<html><body style='background:#f6f7f9;font:18px -apple-system;color:#117f75;padding:100px'>MathM 正在启动本地研究空间…</body></html>", baseURL:nil)
        startBackend()
    }
    func installMenu() {
        let menu = NSMenu(); let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appItem.submenu = appMenu
        appMenu.addItem(withTitle:"关于 MathM",action:#selector(about),keyEquivalent:"")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle:"打开数据目录",action:#selector(openData),keyEquivalent:"d")
        appMenu.addItem(withTitle:"打开模型配置",action:#selector(openConfig),keyEquivalent:",")
        appMenu.addItem(withTitle:"查看运行日志",action:#selector(openLogs),keyEquivalent:"")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle:"退出 MathM",action:#selector(NSApplication.terminate(_:)),keyEquivalent:"q")
        let editItem = NSMenuItem(); menu.addItem(editItem); let edit = NSMenu(title:"编辑");editItem.submenu = edit
        for (name,action,key) in [("撤销","undo:","z"),("剪切","cut:","x"),("复制","copy:","c"),("粘贴","paste:","v"),("全选","selectAll:","a")] {
            edit.addItem(withTitle:name,action:Selector(action),keyEquivalent:key)
        }
        let viewItem=NSMenuItem();menu.addItem(viewItem);let view=NSMenu(title:"视图");viewItem.submenu=view
        view.addItem(withTitle:"重新载入",action:#selector(reload),keyEquivalent:"r")
        view.addItem(withTitle:"放大",action:#selector(zoomIn),keyEquivalent:"+")
        view.addItem(withTitle:"缩小",action:#selector(zoomOut),keyEquivalent:"-")
        NSApp.mainMenu=menu
    }
    @objc func about() {
        NSApp.orderFrontStandardAboutPanel(options:[.applicationName:"MathM",.applicationVersion:(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.5.0"),.credits:NSAttributedString(string:"数模研究工作台\n本地材料 · 真实进度 · 技能审查\n模型连接需自行配置。")])
    }
    @objc func openData() { NSWorkspace.shared.open(support.appendingPathComponent("data")) }
    @objc func openLogs() { NSWorkspace.shared.open(support.appendingPathComponent("logs")) }
    @objc func openConfig() {
        let path=support.appendingPathComponent(".env")
        if !fm.fileExists(atPath:path.path) {
            let text="# 填写后请退出并重新打开 MathM\nMATHM_API_KEY=\nMATHM_BASE_URL=https://api.openai.com/v1\nMATHM_MODEL=\n"
            try? text.write(to:path,atomically:true,encoding:.utf8)
            try? fm.setAttributes([.posixPermissions:0o600],ofItemAtPath:path.path)
        }
        NSWorkspace.shared.open(path)
    }
    @objc func reload() { webView.reload() }
    @objc func zoomIn() { webView.pageZoom = min(1.8,webView.pageZoom+0.1) }
    @objc func zoomOut() { webView.pageZoom = max(0.7,webView.pageZoom-0.1) }
    func startBackend() {
        do {
            guard let resources=Bundle.main.resourceURL else { throw NSError(domain:"MathM",code:1,userInfo:[NSLocalizedDescriptionKey:"应用资源缺失"]) }
            try fm.createDirectory(at:support.appendingPathComponent("logs"),withIntermediateDirectories:true)
            let runDir=support.appendingPathComponent("run/"+UUID().uuidString,isDirectory:true)
            try fm.createDirectory(at:runDir,withIntermediateDirectories:true)
            readyFile=runDir.appendingPathComponent("ready.json")
            let process=Process()
            process.executableURL=resources.appendingPathComponent("runtime/bin/python3.12")
            process.arguments=["-I","-B",resources.appendingPathComponent("backend/desktop_server.py").path]
            var env=ProcessInfo.processInfo.environment
            env["MATHM_DESKTOP_SUPPORT"]=support.path
            env["MATHM_READY_FILE"]=readyFile.path
            env["MATHM_BUNDLED_SKILLS"]=resources.appendingPathComponent("skills").path
            env["PYTHONNOUSERSITE"]="1"
            env.removeValue(forKey:"PYTHONHOME");env.removeValue(forKey:"PYTHONPATH")
            process.environment=env
            let logURL=support.appendingPathComponent("logs/backend.log")
            if !fm.fileExists(atPath:logURL.path) { fm.createFile(atPath:logURL.path,contents:nil) }
            let log=try FileHandle(forWritingTo:logURL);try log.seekToEnd()
            process.standardOutput=log;process.standardError=log
            process.terminationHandler={ [weak self] proc in
                DispatchQueue.main.async {
                    guard let self=self,!self.quitting else{return}
                    self.timer?.invalidate()
                    self.showError("本地服务已停止（退出码 \(proc.terminationStatus)）。可从应用菜单查看运行日志。")
                }
            }
            backend=process;try process.run();started=Date()
            timer=Timer.scheduledTimer(withTimeInterval:0.2,repeats:true){[weak self] _ in self?.checkReady()}
        } catch { showError(error.localizedDescription) }
    }
    func checkReady() {
        if let bytes=try? Data(contentsOf:readyFile),let info=(try? JSONSerialization.jsonObject(with:bytes)) as? [String:Any],let port=info["port"] as? Int {
            timer?.invalidate();currentPort=port
            webView.load(URLRequest(url:URL(string:"http://127.0.0.1:\(port)/")!));return
        }
        if Date().timeIntervalSince(started)>30 { timer?.invalidate();showError("启动超过30秒，请通过应用菜单查看运行日志。") }
    }
    func showError(_ message:String) {
        let alert=NSAlert();alert.messageText="MathM 启动遇到问题";alert.informativeText=message
        alert.addButton(withTitle:"查看日志");alert.addButton(withTitle:"关闭")
        if alert.runModal() == .alertFirstButtonReturn { openLogs() }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication)->Bool { true }
    func applicationWillTerminate(_ notification:Notification) {
        quitting=true;timer?.invalidate()
        if let p=backend,p.isRunning { p.terminate() }
        if let r=readyFile { try? fm.removeItem(at:r.deletingLastPathComponent()) }
    }
    func webView(_ webView:WKWebView,runOpenPanelWith parameters:WKOpenPanelParameters,initiatedByFrame frame:WKFrameInfo,completionHandler:@escaping ([URL]?)->Void) {
        let panel=NSOpenPanel();panel.allowsMultipleSelection=parameters.allowsMultipleSelection;panel.canChooseDirectories=false
        panel.beginSheetModal(for:window){result in completionHandler(result == .OK ? panel.urls:nil)}
    }
    func webView(_ webView:WKWebView,decidePolicyFor navigationAction:WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void) {
        guard let url=navigationAction.request.url else {decisionHandler(.cancel);return}
        if url.scheme=="about" {decisionHandler(.allow);return}
        if url.host=="127.0.0.1" && url.port==currentPort {
            decisionHandler(navigationAction.shouldPerformDownload ? .download:.allow)
        } else {
            if ["https","http"].contains(url.scheme ?? "") {NSWorkspace.shared.open(url)}
            decisionHandler(.cancel)
        }
    }
    func webView(_ webView:WKWebView,navigationAction:WKNavigationAction,didBecome download:WKDownload){download.delegate=self}
    func webView(_ webView:WKWebView,navigationResponse:WKNavigationResponse,didBecome download:WKDownload){download.delegate=self}
    func download(_ download:WKDownload,decideDestinationUsing response:URLResponse,suggestedFilename:String,completionHandler:@escaping(URL?)->Void) {
        let panel=NSSavePanel();panel.nameFieldStringValue=suggestedFilename
        panel.beginSheetModal(for:window){result in completionHandler(result == .OK ? panel.url:nil)}
    }
    func download(_ download:WKDownload,didFailWithError error:Error,resumeData:Data?) {
        let alert=NSAlert();alert.messageText="报告下载未完成";alert.informativeText=error.localizedDescription;alert.runModal()
    }
}
let application=NSApplication.shared
let delegate=AppDelegate()
application.delegate=delegate
application.setActivationPolicy(.regular)
application.run()

// AddWatermark.app — native window for add_watermark.py
//
// Shows the "Add Copyrights Watermark to Image" window (watermark preview,
// file name, image count, "Resize for Sharing" switch, "Change Watermark…",
// Cancel / Submit) and writes the user's choice as JSON to the --out file,
// then quits. Also posts the end-of-task notification (see "Notification mode").
// All image processing stays in add_watermark.py.
//
// Arguments (all "--key value"):
//   --watermark <path>   initially selected SVG/PNG ("" = none)
//   --count <n>          number of images to process (display only)
//   --resize <1|0>       initial state of the switch
//   --resize-max <px>    shown as "(1350px max.)"
//   --dir <path>         folder the "Change Watermark…" panel opens in
//   --out <path>         where to write {"cancelled":…, "path":…, "resize":…}
//
// Build with build_app.sh (needs the Xcode Command Line Tools).

import AppKit
import SwiftUI
import UserNotifications
import UniformTypeIdentifiers

let WINDOW_TITLE = "Add Copyrights Watermark to Image"

// MARK: - Arguments

struct Args {
    var watermark: URL?
    var count = 0
    var resize = true
    var resizeMax = 1350
    var dir: URL?
    var out: URL?
}

func parseArgs() -> Args {
    var args = Args()
    var items = CommandLine.arguments.dropFirst().makeIterator()
    while let key = items.next() {
        guard key.hasPrefix("--"), let value = items.next() else { continue }
        switch key {
        case "--watermark": args.watermark = value.isEmpty ? nil : URL(fileURLWithPath: value)
        case "--count": args.count = Int(value) ?? 0
        case "--resize": args.resize = (value == "1")
        case "--resize-max": args.resizeMax = Int(value) ?? 1350
        case "--dir": args.dir = URL(fileURLWithPath: value, isDirectory: true)
        case "--out": args.out = URL(fileURLWithPath: value)
        default: break
        }
    }
    return args
}

// MARK: - Preview

/// Load a preview image. SVGs are rasterized with rsvg-convert (the same tool
/// add_watermark.py uses), PNGs are loaded directly.
func loadPreview(_ url: URL) -> NSImage? {
    if url.pathExtension.lowercased() == "svg" {
        let tools = ["/opt/homebrew/bin/rsvg-convert", "/usr/local/bin/rsvg-convert"]
        for tool in tools where FileManager.default.isExecutableFile(atPath: tool) {
            let tmp = FileManager.default.temporaryDirectory
                .appendingPathComponent(UUID().uuidString + ".png")
            defer { try? FileManager.default.removeItem(at: tmp) }
            let process = Process()
            process.executableURL = URL(fileURLWithPath: tool)
            process.arguments = ["-w", "256", "-o", tmp.path, url.path]  // 2x the 128 pt preview
            do {
                try process.run()
                process.waitUntilExit()
            } catch {
                continue
            }
            if process.terminationStatus == 0, let data = try? Data(contentsOf: tmp) {
                return NSImage(data: data)
            }
        }
    }
    return NSImage(contentsOf: url)  // PNG, or SVG if this macOS can read it natively
}

// MARK: - Model

@MainActor
final class Model: ObservableObject {
    @Published var watermark: URL? {
        didSet { preview = watermark.flatMap(loadPreview) }
    }
    @Published var preview: NSImage?
    @Published var resize: Bool
    let count: Int
    let resizeMax: Int

    init(args: Args) {
        count = args.count
        resizeMax = args.resizeMax
        resize = args.resize
        watermark = args.watermark
        preview = args.watermark.flatMap(loadPreview)  // didSet doesn't run in init
    }
}

// MARK: - View

enum Field: Hashable {
    case submit, resize, change, cancel
}

struct ContentView: View {
    @ObservedObject var model: Model
    let onChange: () -> Void
    let onCancel: () -> Void
    let onSubmit: () -> Void
    @FocusState private var focus: Field?

    /// Tab order: Submit, Resize switch, Change Watermark, Cancel (Submit skipped while disabled).
    private var order: [Field] {
        model.watermark == nil ? [.resize, .change, .cancel] : [.submit, .resize, .change, .cancel]
    }

    var body: some View {
        DialogLayout(width: 516) {
            HStack(alignment: .top, spacing: 16) {
                thumbnail
                VStack(alignment: .leading, spacing: 10) {
                    ValueRow(label: "File", value: model.watermark?.lastPathComponent ?? "None selected")
                    ValueRow(label: "Apply this watermark to", value: "\(model.count) image(s)")
                    Divider()
                        .padding(.vertical, 2)
                    HStack(spacing: 12) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Resize for Sharing")
                            Text(verbatim: "(\(model.resizeMax)px max.)")  // verbatim: no "1,350" grouping
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        DialogSwitch(label: "Resize for Sharing", isOn: $model.resize)
                            .focused($focus, equals: .resize)
                    }
                }
            }
        } leading: {
            // Non-dismissing action: leading side of the footer (Apple HIG)
            Button("Change Watermark…", action: onChange)
                .focused($focus, equals: .change)
        } trailing: {
            Button("Cancel", action: onCancel)
                .keyboardShortcut(.cancelAction)
                .focused($focus, equals: .cancel)
            Button("Submit", action: onSubmit)
                .keyboardShortcut(.defaultAction)
                .disabled(model.watermark == nil)
                .focused($focus, equals: .submit)
        }
        .modifier(TabOrder(order: order, focus: $focus))
    }

    private var thumbnail: some View {
        ZStack(alignment: .bottomLeading) {
            RoundedRectangle(cornerRadius: 8)
                .fill(Color(nsColor: .quaternaryLabelColor))
            Group {
                if let image = model.preview {
                    Image(nsImage: image)
                        .resizable()
                        .interpolation(.high)
                        .aspectRatio(contentMode: .fit)
                        .padding(6)
                } else {
                    Image(systemName: "photo")
                        .font(.system(size: 32))
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            // Marks where the watermark goes on each image: the bottom-left corner.
            Image(systemName: "square.dashed")
                .font(.system(size: 24, weight: .ultraLight))
                .foregroundStyle(.secondary)
                .padding(6)
        }
        .frame(width: 128, height: 128)
    }
}

// MARK: - App

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let args = parseArgs()
    lazy var model = Model(args: args)
    var window: NSWindow!
    var finished = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        let view = ContentView(
            model: model,
            onChange: { [unowned self] in self.changeWatermark() },
            onCancel: { [unowned self] in self.finish(cancelled: true) },
            onSubmit: { [unowned self] in self.finish(cancelled: false) }
        )
        window = makeDialogWindow(title: WINDOW_TITLE, rootView: view)
        window.delegate = self
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }

    func changeWatermark() {
        let panel = NSOpenPanel()
        panel.message = "Select the watermark image (SVG or PNG)"
        panel.prompt = "Choose"
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.svg, .png]
        panel.directoryURL = model.watermark?.deletingLastPathComponent() ?? args.dir
        panel.beginSheetModal(for: window) { [unowned self] response in
            if response == .OK, let url = panel.url {
                self.model.watermark = url
            }
        }
    }

    /// Write the result for add_watermark.py (once), then quit.
    func finish(cancelled: Bool) {
        guard !finished else { return }
        finished = true
        var result: [String: Any] = ["cancelled": cancelled]
        if !cancelled {
            result["path"] = model.watermark?.path ?? ""
            result["resize"] = model.resize
        }
        if let out = args.out, let data = try? JSONSerialization.data(withJSONObject: result) {
            try? data.write(to: out)
        }
        NSApp.terminate(nil)
    }

    func windowWillClose(_ notification: Notification) {
        finish(cancelled: true)  // red close button = Cancel
    }
}

// MARK: - Shared dialog building blocks (same in the 3 apps, matches the Figma "_Modal")

/// Window chrome of the dialogs: close (= Cancel) and minimize enabled, zoom disabled.
@MainActor
func makeDialogWindow<Content: View>(title: String, rootView: Content) -> NSWindow {
    let controller = NSHostingController(rootView: rootView)
    controller.sizingOptions = .preferredContentSize  // window follows the content height
    let window = NSWindow(contentViewController: controller)
    window.styleMask = [.titled, .closable, .miniaturizable]
    window.title = title
    window.standardWindowButton(.zoomButton)?.isEnabled = false  // no full screen for a dialog
    window.isReleasedWhenClosed = false
    window.level = .floating  // stay above the Finder window it was launched from
    window.center()
    return window
}

/// Main content (40 pt side margins) above the footer actions (20 pt margins):
/// optional leading actions on the left, Cancel / primary action on the right.
struct DialogLayout<Content: View, Leading: View, Trailing: View>: View {
    let width: CGFloat
    let content: Content
    let leading: Leading
    let trailing: Trailing

    init(width: CGFloat,
         @ViewBuilder content: () -> Content,
         @ViewBuilder leading: () -> Leading,
         @ViewBuilder trailing: () -> Trailing) {
        self.width = width
        self.content = content()
        self.leading = leading()
        self.trailing = trailing()
    }

    var body: some View {
        VStack(spacing: 0) {
            content
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 40)
                .padding(.vertical, 20)
            HStack(spacing: 8) {
                leading
                Spacer()
                trailing
            }
            .padding(.horizontal, 20)
            .padding(.top, 12)  // 20 + 12 = 32 pt between the switches and the buttons
            .padding(.bottom, 20)
        }
        .frame(width: width)
    }
}

/// "Label ............ value" line (label primary, value secondary, right aligned).
struct ValueRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack(spacing: 12) {
            Text(label)
            Spacer(minLength: 12)
            Text(verbatim: value)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.middle)
        }
    }
}

/// Small switch with its label hidden visually but kept for VoiceOver.
struct DialogSwitch: View {
    let label: String
    @Binding var isOn: Bool

    var body: some View {
        Toggle(label, isOn: $isOn)
            .toggleStyle(.switch)
            .controlSize(.small)
            .labelsHidden()
    }
}

/// Cycles the focus through `order` with Tab / Shift-Tab (default action button first).
struct TabOrder<Field: Hashable>: ViewModifier {
    let order: [Field]
    var focus: FocusState<Field?>.Binding

    func body(content: Content) -> some View {
        content
            // Shift-Tab can arrive as the "backtab" character (U+0019) instead of Tab + Shift.
            .onKeyPress(keys: [.tab, KeyEquivalent("\u{19}")], phases: .down) { press in
                guard !order.isEmpty else { return .ignored }
                let backward = press.modifiers.contains(.shift) || press.key == KeyEquivalent("\u{19}")
                let index = focus.wrappedValue.flatMap { order.firstIndex(of: $0) }
                    ?? (backward ? 0 : order.count - 1)
                focus.wrappedValue = order[(index + (backward ? order.count - 1 : 1)) % order.count]
                return .handled
            }
            .onAppear {
                // Start on the first field; deferred so the window is key before focus is set.
                DispatchQueue.main.async { focus.wrappedValue = order.first }
            }
    }
}

// MARK: - Notification mode

/// "--notify-title T --notify-body B --out F": post one macOS notification under
/// this app's name (instead of Script Editor's), write {"posted": true|false} to F, quit.
struct NotifyRequest {
    let title: String
    let body: String
    let out: URL?

    static func fromArguments() -> NotifyRequest? {
        var title: String?
        var body = ""
        var out: URL?
        var items = CommandLine.arguments.dropFirst().makeIterator()
        while let key = items.next() {
            guard key.hasPrefix("--"), let value = items.next() else { continue }
            switch key {
            case "--notify-title": title = value
            case "--notify-body": body = value
            case "--out": out = URL(fileURLWithPath: value)
            default: break
            }
        }
        return title.map { NotifyRequest(title: $0, body: body, out: out) }
    }
}

/// Asks macOS to show the banner even though this app is frontmost at that moment
/// (by default, notifications of the active app only go to Notification Center).
final class BannerPresenter: NSObject, UNUserNotificationCenterDelegate {
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification,
                                withCompletionHandler completionHandler:
                                    @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list])
    }
}

@MainActor
final class Notifier: NSObject, NSApplicationDelegate {
    let request: NotifyRequest
    let presenter = BannerPresenter()
    var finished = false

    init(request: NotifyRequest) {
        self.request = request
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        Task { @MainActor in
            finish(posted: await post())
        }
        Task { @MainActor in
            // Give up if the first-time permission prompt is left unanswered.
            try? await Task.sleep(for: .seconds(60))
            finish(posted: false)
        }
    }

    private func post() async -> Bool {
        let center = UNUserNotificationCenter.current()
        center.delegate = presenter
        do {
            // First run only: macOS asks whether this app may send notifications.
            guard try await center.requestAuthorization(options: [.alert, .sound]) else { return false }
            let content = UNMutableNotificationContent()
            content.title = request.title
            content.body = request.body
            try await center.add(UNNotificationRequest(identifier: UUID().uuidString,
                                                       content: content, trigger: nil))
            // Stay alive a moment so macOS can ask the delegate how to present it.
            try? await Task.sleep(for: .seconds(1.5))
            return true
        } catch {
            return false  // e.g. notifications refused for this (locally signed) app
        }
    }

    /// Write the result for the Python script (once), then quit; the notification stays.
    private func finish(posted: Bool) {
        guard !finished else { return }
        finished = true
        if let out = request.out, let data = try? JSONSerialization.data(withJSONObject: ["posted": posted]) {
            try? data.write(to: out)
        }
        NSApp.terminate(nil)
    }
}

/// Launched with no arguments (e.g. by a click on one of its notifications): nothing to do.
@MainActor
final class Quitter: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.terminate(nil)
    }
}

// MARK: - Entry point

// Top-level code runs on the main thread; tell the compiler so it can create the
// @MainActor delegates synchronously.
MainActor.assumeIsolated {
    let app = NSApplication.shared
    let delegate: NSApplicationDelegate  // kept alive by this scope while app.run() blocks
    if let request = NotifyRequest.fromArguments() {
        delegate = Notifier(request: request)
    } else if CommandLine.arguments.contains("--out") {
        delegate = AppDelegate()
    } else {
        delegate = Quitter()
    }
    app.delegate = delegate
    app.run()
}

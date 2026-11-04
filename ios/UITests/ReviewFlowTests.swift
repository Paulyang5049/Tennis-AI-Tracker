import XCTest

final class ReviewFlowTests: XCTestCase {
    func testRemoveAssociationThenCorrectEventType() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launchEnvironment["TENNIS_REVIEW_FIXTURE"] = "Synthetic Correction"
        app.launch()
        let match = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Synthetic Correction")).firstMatch
        XCTAssertTrue(match.waitForExistence(timeout: 20)); match.tap()
        let migration = app.buttons["saveAsV3"]; reveal(migration, in: app); migration.tap()
        let review = app.buttons["Review"]; reveal(review, in: app); review.tap()
        let link = app.buttons["Link shot"]; reveal(link, in: app); link.tap()
        app.descendants(matching: .any)["association.hit"].tap()
        app.buttons["1.00s · shot-1"].tap()
        app.descendants(matching: .any)["association.bounce"].tap()
        app.buttons["2.00s · bounce-1"].tap()
        app.buttons["Confirm fields"].tap()
        let associations = app.buttons["Shot, bounce and rally associations"]
        reveal(associations, in: app); associations.tap()
        app.descendants(matching: .any)["association.existing"].tap()
        app.buttons["shot-1 · bounce-1"].tap()
        app.buttons["association.remove"].tap()
        let allEvents = app.buttons["All events"]; reveal(allEvents, in: app); allEvents.tap()
        let edit = app.buttons["edit.event.shot-1"]; reveal(edit, in: app); edit.tap()
        app.descendants(matching: .any)["event.kind"].tap()
        app.buttons["Bounce"].tap()
        app.buttons["saveEvent"].tap()
        let overview = app.buttons["Overview"]; reveal(overview, in: app); overview.tap()
        let hits = app.buttons["metric.hits"]; reveal(hits, in: app)
        XCTAssertTrue(hits.label.contains("Insufficient data"))
        let menu = app.descendants(matching: .any)["exportMenu"]; reveal(menu, in: app); menu.tap()
        app.buttons["exportReport"].tap(); app.buttons["Prepare export"].tap()
        XCTAssertTrue(app.buttons["shareExport"].waitForExistence(timeout: 30))
        app.terminate()
    }
    func testReopenedOriginalReview() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        app.launch()
        let match = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Synthetic Review · v3")).firstMatch
        XCTAssertTrue(match.waitForExistence(timeout: 20)); match.tap()
        let confirmed = app.buttons["Human confirmed"]; reveal(confirmed, in: app); confirmed.tap()
        let hits = app.buttons["metric.hits"]; reveal(hits, in: app)
        XCTAssertEqual(hits.label, "Shots, 1")
        app.terminate()
    }
    func testEmptyLargeText() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN",
            "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]
        app.launchEnvironment["TENNIS_REVIEW_FIXTURE"] = "Synthetic Empty"
        app.launch()
        let match = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Synthetic Empty")).firstMatch
        XCTAssertTrue(match.waitForExistence(timeout: 20)); match.tap()
        let confirmed = app.buttons["人工已确认"]; reveal(confirmed, in: app)
        XCTAssertGreaterThan(confirmed.frame.height, 35, "Accessibility text size must be active")
        confirmed.tap()
        let hits = app.buttons["metric.hits"]; reveal(hits, in: app)
        XCTAssertTrue(hits.label.contains("暂无足够数据"))
        try app.performAccessibilityAudit(for: [.sufficientElementDescription, .trait, .textClipped])
        let attachment = XCTAttachment(screenshot: app.screenshot()); attachment.lifetime = .keepAlways; add(attachment)
        app.terminate()
    }
    func testReimportedEvidence() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US", "-AppleInterfaceStyle", "Dark"]
        app.launchEnvironment["TENNIS_REVIEW_FIXTURE"] = "Synthetic Reimport"
        app.launch()
        let match = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Synthetic Reimport")).firstMatch
        XCTAssertTrue(match.waitForExistence(timeout: 20)); match.tap()
        let hits = app.buttons["metric.hits"]; reveal(hits, in: app)
        XCTAssertEqual(hits.label, "Shots, 1")
        let unassigned = app.buttons["metric.unassigned_landings"]; reveal(unassigned, in: app)
        XCTAssertTrue(unassigned.label.contains("Insufficient data"))
        let attachment = XCTAttachment(screenshot: app.screenshot()); attachment.lifetime = .keepAlways; add(attachment)
        app.terminate()
    }
    func reveal(_ element: XCUIElement, in app: XCUIApplication) {
        for _ in 0..<12 { if element.isHittable { return }; app.swipeUp() }
        XCTAssertTrue(element.isHittable, app.debugDescription)
    }
    func testReviewLoop() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(en)", "-AppleLocale", "en_US"]
        // Host runner installs a generated public fixture inside the app's sandbox.
        app.launchEnvironment["TENNIS_REVIEW_FIXTURE"] = "Synthetic Review"
        app.launch()
        let match = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Synthetic Review")).firstMatch
        XCTAssertTrue(match.waitForExistence(timeout: 20)); match.tap()
        let migration = app.buttons["saveAsV3"]
        reveal(migration, in: app); migration.tap()
        let settings = app.buttons["matchSettings"]
        XCTAssertTrue(settings.waitForExistence(timeout: 20)); reveal(settings, in: app); settings.tap()
        app.buttons["Confirm fields"].tap()
        XCTAssertTrue(app.buttons["matchSettings"].waitForExistence(timeout: 10))
        let review = app.buttons["Review"]; reveal(review, in: app); review.tap()
        let link = app.buttons["Link shot"]; reveal(link, in: app); link.tap()
        app.descendants(matching: .any)["association.hit"].tap()
        app.buttons["1.00s · shot-1"].tap()
        app.descendants(matching: .any)["association.bounce"].tap()
        app.buttons["2.00s · bounce-1"].tap()
        app.buttons["Confirm fields"].tap()
        XCTAssertTrue(app.buttons["matchSettings"].waitForExistence(timeout: 10))
        let allEvents = app.buttons["All events"]; reveal(allEvents, in: app); allEvents.tap()
        let edit = app.buttons["edit.event.shot-1"]; reveal(edit, in: app); edit.tap()
        let favorite = app.switches["Favorite"].firstMatch
        favorite.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.5)).tap()
        XCTAssertEqual(favorite.value as? String, "1")
        app.buttons["saveEvent"].tap()
        XCTAssertTrue(app.buttons["matchSettings"].waitForExistence(timeout: 10))
        app.buttons["Court"].tap()
        XCTAssertTrue(app.staticTexts["Landing distribution"].waitForExistence(timeout: 10))
        app.buttons["Overview"].tap()
        let hits = app.buttons["metric.hits"]
        for _ in 0..<10 { if hits.isHittable { break }; app.swipeDown() }
        XCTAssertTrue(hits.waitForExistence(timeout: 10)); hits.tap()
        let evidence = app.buttons["evidence.event.shot-1"]
        XCTAssertTrue(evidence.waitForExistence(timeout: 10)); evidence.tap()
        for kind in ["exportReport", "exportClip", "exportPackage"] {
            let menu = app.descendants(matching: .any)["exportMenu"]; reveal(menu, in: app); menu.tap()
            app.buttons[kind].tap(); app.buttons["Prepare export"].tap()
            XCTAssertTrue(app.buttons["shareExport"].waitForExistence(timeout: 30))
        }
        let attachment = XCTAttachment(screenshot: app.screenshot()); attachment.lifetime = .keepAlways; add(attachment)
        app.terminate()
    }
}

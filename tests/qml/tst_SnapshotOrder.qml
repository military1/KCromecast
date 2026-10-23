import QtQuick
import QtTest
import "../../package/contents/ui/SnapshotOrder.js" as SnapshotOrder

TestCase {
    name: "SnapshotOrder"
    function test_late_http_response_from_an_old_service_is_ignored() {
        var order = SnapshotOrder.create();
        verify(SnapshotOrder.accept(order, {instance: "old", revision: 500, sampled_at: 100}));
        verify(SnapshotOrder.accept(order, {instance: "new", revision: 1, sampled_at: 101}));
        verify(!SnapshotOrder.accept(order, {instance: "old", revision: 501, sampled_at: 102}));
        compare(order.instance, "new");
    }
    function test_out_of_order_events_and_position_updates() {
        var order = SnapshotOrder.create();
        verify(SnapshotOrder.accept(order, {instance: "service", revision: 4, sampled_at: 100}));
        verify(!SnapshotOrder.accept(order, {instance: "service", revision: 3, sampled_at: 101}));
        verify(!SnapshotOrder.accept(order, {instance: "service", revision: 4, sampled_at: 99}));
        verify(SnapshotOrder.accept(order, {instance: "service", revision: 4, sampled_at: 102}));
    }
}

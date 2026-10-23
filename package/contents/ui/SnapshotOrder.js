.pragma library

function create() {
    return {instance: "", revision: -1, sampledAt: 0, retired: []};
}

function accept(state, snapshot) {
    if (typeof snapshot.instance !== "string" || !snapshot.instance.length) return false;
    if (state.retired.indexOf(snapshot.instance) >= 0) return false;
    var revision = Number(snapshot.revision) || 0;
    var sampledAt = Number(snapshot.sampled_at) || 0;
    if (snapshot.instance === state.instance) {
        if (revision < state.revision || (revision === state.revision && sampledAt < state.sampledAt)) return false;
    } else if (state.instance.length) {
        state.retired = state.retired.concat([state.instance]).slice(-16);
    }
    state.instance = snapshot.instance;
    state.revision = revision;
    state.sampledAt = sampledAt;
    return true;
}

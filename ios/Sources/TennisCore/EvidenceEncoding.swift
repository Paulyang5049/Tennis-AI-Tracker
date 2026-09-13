import Foundation

// Explicit nulls are required by the shared interchange schemas. Codable's
// default encodeIfPresent would silently omit these required nullable fields.

extension AnalysisEvent {
    enum CodingKeys: String, CodingKey { case id, kind, start, end, scene, playerId, stroke, position, provenance, reviewed, confidence, excluded, favorite, participantId, contactInterval, contactPointImagePx, hitterPositionCourtM, fieldConfidence, positionSource }
    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(kind, forKey: .kind)
        try container.encode(start, forKey: .start)
        try container.encode(end, forKey: .end)
        try container.encode(scene, forKey: .scene)
        try container.encode(playerId, forKey: .playerId)
        try container.encode(stroke, forKey: .stroke)
        try container.encode(position, forKey: .position)
        try container.encode(provenance, forKey: .provenance)
        try container.encode(reviewed, forKey: .reviewed)
        try container.encode(confidence, forKey: .confidence)
        try container.encode(excluded, forKey: .excluded)
        try container.encode(favorite, forKey: .favorite)
        try container.encodeIfPresent(participantId, forKey: .participantId)
        try container.encodeIfPresent(contactInterval, forKey: .contactInterval)
        try container.encodeIfPresent(contactPointImagePx, forKey: .contactPointImagePx)
        try container.encodeIfPresent(hitterPositionCourtM, forKey: .hitterPositionCourtM)
        try container.encodeIfPresent(fieldConfidence, forKey: .fieldConfidence)
        try container.encodeIfPresent(positionSource, forKey: .positionSource)
    }
}

extension SceneRoleAssignment {
    enum CodingKeys: String, CodingKey { case id, scene, start, end, trackId, side, participantId, reviewed, confidence }
    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(scene, forKey: .scene)
        try container.encode(start, forKey: .start)
        try container.encode(end, forKey: .end)
        try container.encode(trackId, forKey: .trackId)
        try container.encode(side, forKey: .side)
        try container.encode(participantId, forKey: .participantId)
        try container.encode(reviewed, forKey: .reviewed)
        try container.encode(confidence, forKey: .confidence)
    }
}

extension ShotBounceLink {
    enum CodingKeys: String, CodingKey { case id, shotId, bounceId, reviewed, confidence }
    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(shotId, forKey: .shotId)
        try container.encode(bounceId, forKey: .bounceId)
        try container.encode(reviewed, forKey: .reviewed)
        try container.encode(confidence, forKey: .confidence)
    }
}

extension RallyEvidence {
    enum CodingKeys: String, CodingKey { case id, start, end, shotIds, reviewed, outcome }
    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(start, forKey: .start)
        try container.encode(end, forKey: .end)
        try container.encode(shotIds, forKey: .shotIds)
        try container.encode(reviewed, forKey: .reviewed)
        try container.encode(outcome, forKey: .outcome)
    }
}

extension EvidenceMetric {
    enum CodingKeys: String, CodingKey { case id, definition, version, view, value, numerator, denominator, eventIds, excludedEventIds, inputDigest, reviewPolicyVersion }
    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(definition, forKey: .definition)
        try container.encode(version, forKey: .version)
        try container.encode(view, forKey: .view)
        try container.encode(value, forKey: .value)
        try container.encode(numerator, forKey: .numerator)
        try container.encode(denominator, forKey: .denominator)
        try container.encode(eventIds, forKey: .eventIds)
        try container.encode(excludedEventIds, forKey: .excludedEventIds)
        try container.encode(inputDigest, forKey: .inputDigest)
        try container.encode(reviewPolicyVersion, forKey: .reviewPolicyVersion)
    }
}

extension PlayerPosition {
    enum CodingKeys: String, CodingKey { case schemaVersion, timestamp, scene, trackId, side, positionCourtM, method, reviewed, calibrationId, imagePointPx, errorM, roleState }
    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(timestamp, forKey: .timestamp)
        try container.encode(scene, forKey: .scene)
        try container.encode(trackId, forKey: .trackId)
        try container.encode(side, forKey: .side)
        try container.encode(positionCourtM, forKey: .positionCourtM)
        try container.encode(method, forKey: .method)
        try container.encode(reviewed, forKey: .reviewed)
        try container.encode(calibrationId, forKey: .calibrationId)
        try container.encodeIfPresent(imagePointPx, forKey: .imagePointPx)
        try container.encodeIfPresent(errorM, forKey: .errorM)
        try container.encodeIfPresent(roleState, forKey: .roleState)
    }
}

extension EvidenceCorrection {
    enum CodingKeys: String, CodingKey { case schemaVersion, id, sequence, entityId, actor, timestamp, reason, before, after, entityType }
    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion)
        try container.encode(id, forKey: .id)
        try container.encode(sequence, forKey: .sequence)
        try container.encode(entityId, forKey: .entityId)
        try container.encode(actor, forKey: .actor)
        try container.encode(timestamp, forKey: .timestamp)
        try container.encode(reason, forKey: .reason)
        try container.encode(before, forKey: .before)
        try container.encode(after, forKey: .after)
        try container.encodeIfPresent(entityType, forKey: .entityType)
    }
}

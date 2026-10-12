# Known Data Models for Professor-University Graphs

This document catalogs the data layouts observed or anticipated in the
sparql-professors-universities task family. Each model describes the triples
used for professor identification, affiliation, and naming.

## Model A: String Roles + Department-Mediated Affiliation (v01)

**Professor identification:**
```turtle
uni:Alex_Morgan a uni:Person ;
    uni:hasName "Alex Morgan" ;
    uni:role "Professor of Computer Science" .

uni:Thomas_Berger a uni:Person ;
    uni:hasName "Thomas Berger" ;
    uni:role "Assistant Professor of Computer Science" .
```

**Affiliation chain:**
```turtle
uni:Alex_Morgan uni:worksAt uni:ComputerScience_NTUA .
uni:ComputerScience_NTUA a uni:Department ;
    uni:partOfUniversity uni:NTUA .
uni:NTUA a uni:University ;
    uni:hasName "National Technical University of Athens" .
```

**Non-qualifying roles:**
```turtle
uni:Jane_Petterson a uni:Person ;
    uni:hasName "Jane Petterson" ;
    uni:role "Lecturer" .

uni:Student1 a uni:Person ;
    uni:hasName "Sophia Müller" ;
    uni:role "Student" .
```

**Key characteristics:**
- Roles are string literals on `uni:role`
- Qualifying strings contain "Professor" (both "Professor of X" and "Assistant Professor of X")
- Affiliation is two-hop: person → department (via `uni:worksAt`) → university (via `uni:partOfUniversity`)
- University name via `uni:hasName`

---

## Model B: String Roles + Direct University Affiliation

**Professor identification:** Same as Model A (string roles)

**Affiliation chain:**
```turtle
uni:SomeProf a uni:Person ;
    uni:hasName "Some Professor" ;
    uni:role "Professor" ;
    uni:worksAt uni:SomeUniversity .

uni:SomeUniversity a uni:University ;
    uni:hasName "Some University" .
```

**Key characteristics:**
- No intermediate department
- `uni:worksAt` points directly to a `uni:University` resource
- Need type check: `?university a uni:University`

---

## Model C: Resource-Based Ranks

**Professor identification:**
```turtle
uni:Rank_Professor a uni:AcademicRank ;
    uni:rankLabel "Professor" .

uni:Rank_AsstProf a uni:AcademicRank ;
    uni:rankLabel "Assistant Professor" .

uni:SomeProf a uni:Person ;
    uni:hasName "Some Professor" ;
    uni:hasAcademicRank uni:Rank_Professor .
```

**Key characteristics:**
- Ranks are resources, not strings
- Must follow `uni:hasAcademicRank` to a rank resource, then `uni:rankLabel` to a string
- Qualifying labels: "Professor", "Assistant Professor", etc.

---

## Model D: Appointment-Based Affiliation

**Affiliation chain:**
```turtle
uni:SomeProf a uni:Person ;
    uni:hasName "Some Professor" ;
    uni:hasAppointment uni:Appt001 .

uni:Appt001 a uni:Appointment ;
    uni:atOrganization uni:SomeUniversity ;
    uni:withRank uni:Rank_Professor .

uni:SomeUniversity a uni:University ;
    uni:hasName "Some University" .
```

**Key characteristics:**
- Affiliation is reified as an appointment resource
- `uni:hasAppointment` → appointment → `uni:atOrganization` → university
- May also carry rank information in the appointment

---

## Model E: Inverse Containment

**Affiliation chain:**
```turtle
uni:SomeProf a uni:Person ;
    uni:hasName "Some Professor" ;
    uni:worksAt uni:SomeDept .

uni:SomeUniversity a uni:University ;
    uni:hasName "Some University" ;
    uni:hasDepartment uni:SomeDept .
```

**Key characteristics:**
- Department → university link is inverse: `uni:hasDepartment` instead of `uni:partOfUniversity`
- Direction of triple is reversed

---

## Model F: Mixed/Heterogeneous

**Key characteristics:**
- Some professors have `uni:role` strings, others have `uni:hasAcademicRank` resources
- Some affiliations go through departments, others are direct
- May need UNION patterns to capture all professors
- SELECT DISTINCT is critical to avoid duplicates from overlapping patterns

---

## Model G: Teaching Fallback

**Affiliation chain (fallback):**
```turtle
uni:SomeProf a uni:Person ;
    uni:hasName "Some Professor" ;
    uni:role "Professor" ;
    uni:teaches uni:Course101 .
    # Note: no uni:worksAt triple

uni:Course101 a uni:Course ;
    uni:isTaughtIn uni:SomeDept .

uni:SomeDept a uni:Department ;
    uni:partOfUniversity uni:SomeUniversity .
```

**Key characteristics:**
- Some professors lack `uni:worksAt` but can be linked via courses they teach
- Fallback path: person → teaches → course → isTaughtIn → department → partOfUniversity → university
- Primary path via `uni:worksAt` should be tried first

---

## Predicate Summary Table

| Predicate | Domain | Range | Used In |
|-----------|--------|-------|---------|
| `uni:role` | Person | xsd:string (literal) | A, B |
| `uni:hasAcademicRank` | Person | AcademicRank (resource) | C |
| `uni:rankLabel` | AcademicRank | xsd:string | C |
| `uni:worksAt` | Person | Department or University | A, B, E |
| `uni:partOfUniversity` | Department | University | A, E |
| `uni:hasDepartment` | University | Department | E |
| `uni:hasAppointment` | Person | Appointment | D |
| `uni:atOrganization` | Appointment | Organization | D |
| `uni:hasName` | Person/University | xsd:string | All models |
| `uni:teaches` | Person | Course | G (fallback) |
| `uni:isTaughtIn` | Course | Department | G (fallback) |

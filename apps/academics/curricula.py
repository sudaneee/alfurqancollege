"""Official curriculum data transcribed from the documents in /resources.

Course codes, titles, hours and credit units are reproduced exactly as printed,
including apparent errors in the source documents. Those are listed in
SOURCE_NOTES so the Academic Office can confirm or correct them from the
dashboard (Academic setup → Courses). Nothing here is invented.

Course tuple: (code, title, L, T, P, contact_hours, credit_units, type)
"""

NBTE_9_BAND = {
    "name": "NBTE ND 4-point scale (9 bands)",
    "source": "NBTE ND curricula — Nutrition & Dietetics (2018) §8.0; Health Information Management (2022) §16.0",
    "pass_mark": 40,
    "bands": [(75, 100, "A", "4.00", ""), (70, 74, "AB", "3.50", ""), (65, 69, "B", "3.25", ""),
              (60, 64, "BC", "3.00", ""), (55, 59, "C", "2.75", ""), (50, 54, "CD", "2.50", ""),
              (45, 49, "D", "2.25", ""), (40, 44, "E", "2.00", ""), (0, 39, "F", "0.00", "")],
    "classes": [("3.50", "4.00", "Distinction"), ("3.00", "3.49", "Upper Credit"), ("2.50", "2.99", "Lower Credit"),
                ("2.00", "2.49", "Pass"), ("0.00", "1.99", "Fail")],
}

CHPRBN_6_BAND = {
    "name": "CHPRBN Diploma 4-point scale (pass mark 50)",
    "source": "CHPRBN Curriculum for Diploma in Community Health (2022), Certification — Table 1",
    "pass_mark": 50,
    "bands": [(70, 100, "A", "4.00", "Excellent"), (65, 69, "B", "3.50", "Very good"), (60, 64, "C", "3.00", "Good"),
              (55, 59, "D", "2.50", "Fair"), (50, 54, "E", "2.00", "Pass"), (0, 49, "F", "0.00", "Failure")],
    "classes": [("3.50", "4.00", "Distinction"), ("3.00", "3.49", "Upper Credit"), ("2.50", "2.99", "Lower Credit"),
                ("2.00", "2.49", "Pass"), ("0.00", "1.99", "Fail")],
}

PROGRAMMES = [
    {
        "code": "PHT", "name": "Public Health Technology", "slug": "public-health-technology",
        "department": ("Public Health Technology", "PHT"),
        "award_title": "National Diploma (ND) in Public Health Technology",
        "regulatory_body": "NBTE in collaboration with EHORECON",
        "curriculum_reference": "NBTE Curriculum and Course Specification for ND Public Health Technology (March 2021)",
        "pdf": "Public Health Curriculum.pdf",
        "duration_years": 2, "level_names": "ND I, ND II", "scheme": "nbte",
        "ca": 30, "exam": 70, "min_total": 72, "max_total": 80, "icon": "bi-shield-plus", "order": 1,
        "summary": "The National Diploma Programme in Public Health Technology is designed to provide basic academic and "
                   "professional training required to assist in achieving Public Health at the community level.",
        "goal": "To provide basic academic and professional training required to assist in achieving Public Health at the community level.",
        "objectives": "Acquire basic skills in Public Health\nCarry out community diagnosis and mobilization\n"
                      "Conduct Health Education and promotion in the community\nCollect, analyse and present health data\n"
                      "Assist in sensitizing and counseling community members to actively participate in Public Health programmes\n"
                      "Participate in preventive and promotive health care service delivery",
        "entry_requirements": "Five (5) credit passes in WASC, NECO or GCE 'O' Level at not more than two (2) sittings\n"
                              "Subjects must include English, Mathematics, Biology/Health Science, Chemistry and Physics\n"
                              "Or: Environmental Health Assistant Certificate (CGPA not less than 2.50) from an accredited programme/institution",
        "structure_notes": "Two (2) years (four semesters) of classroom work, laboratory and field practicum. Each semester lasts 17–18 weeks: "
                           "15 contact weeks of teaching and 2–3 weeks for registration, continuous assessment and examinations. "
                           "The programme incorporates 3–4 months of SIWES at the end of the second semester of the second year.",
        "assessment_notes": "Theory: class work 10, examination 30. Practical: class work/laboratory 20, examination 40. "
                            "Combined: continuous assessment 30, examinations 70.",
        "award_conditions": "Satisfactory performance in all prescribed course work, continuous assessment, workshop practices, laboratory work and field trips\n"
                            "Satisfactory performance in all semester examinations\nSatisfactory completion of written project/seminar papers\n"
                            "A minimum of 72 and a maximum of 80 semester credit units\n"
                            "Pass the EHORECON professional certification examination in the second semester of ND II",
        "practicals": [
            ("siwes", "Supervised Industrial Work Experience Scheme (SIWES)", 2, 2, "End of the second semester of the second year", "3–4 months", ""),
            ("project", "Final year project (PHT 227)", 2, 2, "ND II second semester", "", "Individual or group (maximum 2 per group), supervised and graded by institutional format."),
            ("licensing", "EHORECON professional certification examination", 2, 2, "Second semester of ND II", "",
             "Oral examination, practical examination, and theory (essay and 50 MCQ)."),
        ],
        "courses": {
            (1, 1): [("PHT 111", "Introduction to Public Health", 2, None, 1, 45, 3, "professional"),
                     ("MTH 101", "General Mathematics", 2, 1, None, 45, 3, "foundation"),
                     ("STA 101", "Introduction to Statistics", 2, None, None, 30, 2, "foundation"),
                     ("GNS 230", "General Biology", 1, None, 1, 30, 2, "foundation"),
                     ("GST 101", "Use of English", 2, None, None, 30, 2, "general"),
                     ("PHS 111", "Introduction to Pharmacology and Therapeutics", 2, None, None, 30, 2, "professional"),
                     ("COM 111", "Introduction to Computer Science", 1, None, 2, 45, 3, "foundation"),
                     ("PHT 112", "Immunology and Immunization", 2, None, 1, 45, 3, "professional"),
                     ("GLT 111", "General Laboratory Technique", 1, None, 2, 45, 3, "foundation"),
                     ("DTH 115", "Introduction to Anatomy and Physiology", 2, None, 1, 45, 3, "foundation"),
                     ("GNS 127", "Citizenship Education 1", 2, None, None, 30, 2, "general")],
            (1, 2): [("GNS 213", "Introduction to Medical Sociology", 2, None, None, 30, 2, "general"),
                     ("PHT 121", "Introduction to Health Education and Promotion", 2, None, 1, 45, 3, "professional"),
                     ("GNS 112", "Introduction to General Chemistry", 2, None, 1, 45, 3, "foundation"),
                     ("PHT 122", "Introduction to Biostatistics", 2, None, 1, 45, 3, "professional"),
                     ("EHT 125", "Public Health Nutrition", 3, None, None, 45, 3, "professional"),
                     ("PHT 124", "Substance Use and Abuse", 2, None, None, 30, 2, "professional"),
                     ("EHT 111", "Introduction to Environmental Health", 2, None, 1, 45, 3, "professional"),
                     ("PHT 126", "Introduction to Demography", 2, None, None, 30, 2, "professional"),
                     ("CHO 136", "Introduction to Mental Health", 2, None, None, 30, 2, "professional"),
                     ("EHT 212", "Introduction to Epidemiology", 2, None, None, 30, 2, "professional"),
                     ("EED 126", "Introduction to Entrepreneurship Education", 1, None, 1, 30, 2, "general")],
            (2, 1): [("PHT 201", "Introduction to Community Health", 2, None, None, 30, 2, "professional"),
                     ("PHT 211", "Introduction to Communicable and Non Communicable Disease", 3, None, None, 45, 3, "professional"),
                     ("PHT 212", "Primary Health Care", 2, None, 1, 45, 3, "professional"),
                     ("GNS 218", "Research Methodology", 2, None, None, 30, 2, "general"),
                     ("PHT 213", "Introduction to Emergency Response", 1, None, 1, 30, 2, "professional"),
                     ("PHT 214", "Maternal and Child Health", 2, None, 1, 45, 3, "professional"),
                     ("STB 211", "Introduction to Microbiology and Parasitology", 2, None, 1, 45, 3, "foundation"),
                     ("PHT 216", "Seminar in Public Health", 1, None, 1, 30, 2, "seminar"),
                     ("EED 216", "Practice of Entrepreneurship", 1, None, 1, 30, 2, "general")],
            (2, 2): [("PHT 221", "Public Health Planning and Management", 3, None, None, 45, 3, "professional"),
                     ("PHT 222", "First Aid", 2, None, 1, 45, 3, "professional"),
                     ("EHT 211", "Introduction to Public Health Pest Management", 2, None, 1, 45, 3, "professional"),
                     ("EHT 223", "Public/Environmental Health Laws", 2, None, 1, 45, 3, "professional"),
                     ("PHT 225", "Global and Contemporary Health Issues", 2, None, None, 30, 2, "professional"),
                     ("EHT 315", "Health Economics", 2, None, None, 30, 2, "professional"),
                     ("PHT 227", "Project", 2, None, 4, 90, 6, "project")],
        },
    },
    {
        "code": "NUD", "name": "Nutrition and Dietetics", "slug": "nutrition-and-dietetics",
        "department": ("Nutrition and Dietetics", "NUD"),
        "award_title": "National Diploma (ND) in Nutrition and Dietetics",
        "regulatory_body": "National Board for Technical Education (NBTE)",
        "curriculum_reference": "NBTE National Diploma in Nutrition and Dietetics — Curriculum and Course Specifications (2018)",
        "pdf": "Curriculum for ND Nutrition & Dietetics courses NBTE_044641.pdf",
        "duration_years": 2, "level_names": "ND I, ND II", "scheme": "nbte",
        "ca": 30, "exam": 70, "min_total": 80, "max_total": 120, "icon": "bi-egg-fried", "order": 2,
        "summary": "This programme is designed to produce Diplomates capable of assisting Nutritionists and Dietitians in planning and "
                   "executing nutrition activities for clients and patients in institutions and communities.",
        "goal": "To produce Diplomates capable of assisting Nutritionists and Dietitians in planning and executing nutrition activities "
                "for clients and patients in institutions and communities.",
        "objectives": "Prepare therapeutic diets to prescription\nUndertake nutrition and dietetics research (including field survey) under supervision\n"
                      "Assist in the planning of menu in various organizations and institutions\n"
                      "Assist in diet supervision in hospitals, hotels, schools, industries, canteens and social welfare agencies\n"
                      "Participate in planning and implementation of nutrition education programmes at facility and community levels\n"
                      "Assist in formulating food and food products and assessing their nutritional qualities\n"
                      "Assist in the management of nutritional diseases",
        "entry_requirements": "GCE O'Level, SSCE, NTC or equivalent with credit passes in five relevant subjects at not more than two sittings\n"
                              "Subjects: Mathematics, English Language, Biology, Chemistry\n"
                              "And any one of: Agricultural Science, Physics, Food and Nutrition, Geography, Economics",
        "structure_notes": "Four semesters of classroom, laboratory and workshop activities, and a semester (3–4 months) of SIWES. "
                           "Each semester is 17 weeks: 15 contact weeks of teaching and 2 weeks for registration, tests, revision and examination. "
                           "SIWES takes place at the end of the second semester of the first year.",
        "assessment_notes": "The curriculum does not prescribe a CA/examination split; 30/70 is the initial configuration and can be changed by the Academic Office.",
        "award_conditions": "Pass prescribed course work, examinations, diploma project and the supervised industrial work experience\n"
                            "Complete a minimum of 80–120 semester credit units",
        "practicals": [
            ("siwes", "Students Industrial Work Experience Scheme (SIWES)", 1, 2, "Long vacation after the second semester of the first year", "3–4 months",
             "Graded pass/fail. Weighted parameters: punctuality 10, attendance 10, general attitude to work 10, respect for authority 10, "
             "interest in the field 10, technical competence 10 (total 60%), plus log book. Three supervisory visits."),
            ("project", "Project (NUD 245)", 2, 2, "ND II second semester", "", ""),
        ],
        "courses": {
            (1, 1): [("GNS 101", "Use of English I", 2, None, None, None, 2, "general"),
                     ("GNS 111", "Citizenship Education I", 2, None, None, None, 2, "general"),
                     ("STB 112", "Morphology and Physiology of Living Things", 2, None, 2, None, 3, "foundation"),
                     ("BCH 121", "Introduction to Biochemistry", 2, None, 3, None, 3, "foundation"),
                     ("STA 111", "Introduction to Statistics", 2, None, None, None, 2, "foundation"),
                     ("FST 122", "Basic Principle of Food Processing & Preservation", 2, None, 2, None, 3, "foundation"),
                     ("AGR 101", "Introduction to Agriculture", 2, None, 2, None, 3, "foundation"),
                     ("NUD 111", "Introduction to Human Nutrition and Dietetics", 2, None, None, None, 2, "professional"),
                     ("NUD 112", "Food formulation and organoleptic evaluation", 2, None, 3, None, 3, "professional")],
            (1, 2): [("GNS 101", "Citizenship Education II", 2, None, None, None, 2, "general"),
                     ("GNS 102", "Communication in English I", 2, None, None, None, 2, "general"),
                     ("EED 126", "Intro. Entrepreneurship", 2, None, None, None, 2, "general"),
                     ("FST 121", "Food Chemistry", 2, None, 2, None, 3, "foundation"),
                     ("FST 214", "Intro to Food Microbiology", 1, None, 2, None, 2, "foundation"),
                     ("NUD 121", "Human Anatomy and Physiology", 1, None, 2, None, 2, "professional"),
                     ("NUD 122", "Human Nutrition and Dietetics", 2, None, None, None, 2, "professional"),
                     ("NUD 123", "Food science and nutrition", 2, None, 2, None, 3, "professional"),
                     ("NUD 124", "Food Preparation and Service", 2, None, 3, None, 3, "professional")],
            (2, 1): [("GNS 121", "Introduction to Sociology", 2, None, None, None, 2, "general"),
                     ("GNS 201", "Use of English II", 2, None, None, None, 2, "general"),
                     ("EED 216", "Practice of Entrepreneurship", 2, None, 2, None, 2, "general"),
                     ("NUD 231", "Human Physiology", 2, None, 2, None, 2, "professional"),
                     ("NUD 232", "Human Nutrition II", 1, None, 2, None, 3, "professional"),
                     ("NUD 233", "Clinical Diseases and Diet Therapy I", 2, None, 3, None, 3, "professional"),
                     ("NUD 234", "Nutrient Metabolism", 3, None, 3, None, 3, "professional"),
                     ("NUD 235", "Community Nutrition", 2, None, 3, None, 2, "professional"),
                     ("NUD 236", "Elements of Public Health Nutrition", 2, None, 2, None, 2, "professional"),
                     ("NUD 237", "Research Methods", 2, None, None, None, 2, "professional")],
            (2, 2): [("GNS 202", "Communication in English II", 2, None, None, None, 2, "general"),
                     ("MAN 201", "Business Management", 2, None, None, None, 2, "general"),
                     ("FST 223", "Introduction to Food Packaging", 2, None, None, None, 2, "foundation"),
                     ("NUD 241", "Human Nutrition III", 2, None, 2, None, 2, "professional"),
                     ("NUD 242", "Clinical Disease and Diet Therapy II", 2, None, 4, None, 3, "professional"),
                     ("NUD 243", "Introduction to food analysis", 1, None, 2, None, 2, "professional"),
                     ("NUD 244", "Seminar", None, 1, None, None, 1, "seminar"),
                     ("NUD 245", "Project", None, None, None, None, 6, "project")],
        },
    },
    {
        "code": "HIM", "name": "Health Information Management", "slug": "health-information-management",
        "department": ("Health Information Management", "HIM"),
        "award_title": "National Diploma (ND) in Health Information Management",
        "regulatory_body": "NBTE; indexing and licensing by HRORBN",
        "curriculum_reference": "NBTE National Diploma in Health Information Management — Curriculum and Course Specifications (November 2022)",
        "pdf": "NEW-ND HIM CURRICULUM.pdf",
        "duration_years": 2, "level_names": "ND I, ND II", "scheme": "nbte",
        "ca": 30, "exam": 70, "min_total": 0, "max_total": 0, "icon": "bi-clipboard2-pulse", "order": 3,
        "summary": "The National Diploma in Health Information Management is designed to produce technicians equipped with the knowledge "
                   "and skills to plan, collate, organize, disseminate, monitor and manage vital information required at the Local, State "
                   "and National levels in order to ensure effective and comprehensive national health care delivery.",
        "goal": "To produce technicians equipped with the knowledge and skills to plan, collate, organize, disseminate, monitor and manage "
                "vital health information at Local, State and National levels.",
        "objectives": "Assist in planning and organizing health information services in health care delivery system\n"
                      "Organize and control health records, under supervision, in health and medical establishments\n"
                      "Collect, store, retrieve and preserve health information under supervision\n"
                      "Collate, analyze and present health statistical data under supervision\n"
                      "Participate in planning, quality control, evaluation, researches in health care delivery and serve on committees defining standards for health information management\n"
                      "Assist in designing, standardizing and controlling health records forms\nSet up and manage an enterprise",
        "entry_requirements": "A minimum of 5 credit passes in relevant subjects at not more than two (2) sittings at SSCE, WASSCE or equivalent\n"
                              "Subjects must include Mathematics, English Language, Biology, Physics and Chemistry\n"
                              "At least a minimum score in the UTME",
        "structure_notes": "Two academic sessions of four semesters (not less than 17 weeks per semester) including supervised clinical work "
                           "experience (SIWES). All newly admitted students must be indexed by the HRORBN within the first semester.",
        "assessment_notes": "The curriculum does not prescribe a CA/examination split; 30/70 is the initial configuration and can be changed by the Academic Office.",
        "award_conditions": "Pass the prescribed course work, examinations, diploma project, SIWES and attendance requirements\n"
                            "Write and pass the HRORBN Practicing Licensing Examinations part 1 at the end of the programme",
        "practicals": [
            ("siwes", "SIWES (HIM 122) — six weeks", 1, 2, "End of the second semester of the first year, at an HRORBN-accredited health facility", "6 weeks",
             "Logbook evaluation 50%, student's report 30%, confidential report 20%."),
            ("project", "Research Project (HIM 223)", 2, 2, "ND II second semester", "", "Reporting must be undertaken individually."),
            ("licensing", "HRORBN Practicing Licensing Examination part 1", 2, 2, "End of the programme", "", ""),
        ],
        "courses": {
            (1, 1): [("HIM 111", "Health Information Management I", 2, 0, 1, 3, 3, "professional"),
                     ("HIM 112", "Language of Medicine", 1, 0, 1, 2, 2, "professional"),
                     ("HIM 113", "Communication in Health Information Management", 2, 0, 1, 3, 3, "professional"),
                     ("HIS 111", "Mathematics for Health Information Management", 2, 0, 1, 3, 3, "foundation"),
                     ("EHT 212", "Principles of Epidemiology and Disease Control", 2, 0, 0, 2, 2, "foundation"),
                     ("DTE 114", "Introduction to Human Anatomy and Physiology", 1, 0, 1, 2, 2, "foundation"),
                     ("HIS 112", "Statistics for HIM", 2, 0, 1, 3, 3, "professional"),
                     ("COM 111", "Introduction to Computing", 2, 0, 1, 3, 3, "foundation"),
                     ("GNS 101", "Use of English I", 2, 0, 0, 2, 2, "general"),
                     ("GNS 111", "Citizenship Education", 2, 0, 0, 2, 2, "general")],
            (1, 2): [("HIM 121", "Disease Classification and Clinical Coding I", 1, 0, 1, 2, 2, "professional"),
                     ("HIS 121", "Health Planning and Management I", 2, 0, 0, 2, 2, "professional"),
                     ("HIS 122", "Statistical Theory for HIM", 2, 0, 1, 3, 3, "professional"),
                     ("HIS 123", "Introduction to Programming", 2, 0, 1, 3, 3, "professional"),
                     ("HIS 124", "Computer Packages I", 1, 0, 1, 2, 2, "professional"),
                     ("HIS 125", "Primary Health Care for HIM I", 1, 0, 1, 2, 2, "professional"),
                     ("STA 123", "Demography I", 0, 0, 3, 3, 3, "foundation"),
                     ("ENT 126", "Introduction to Entrepreneurship I", 2, 0, 1, 3, 3, "general"),
                     ("GNS 102", "Communication in English I", 2, 0, 0, 2, 2, "general"),
                     ("GNS 121", "Citizenship Education II", 2, 0, 0, 2, 2, "general"),
                     ("HIM 122", "SIWES", 0, 0, 3, 3, 3, "siwes")],
            (2, 1): [("HIM 211", "Health Information Management II", 2, 0, 1, 3, 3, "professional"),
                     ("HIM 212", "Disease Classification and Clinical Coding II", 1, 0, 2, 3, 3, "professional"),
                     ("HIM 213", "Record Documentation Systems", 2, 0, 0, 2, 2, "professional"),
                     ("HIS 211", "Health Informatics I", 2, 0, 0, 2, 2, "professional"),
                     ("HIS 212", "Database Management Systems I", 2, 0, 0, 2, 2, "professional"),
                     ("HIS 214", "Monitoring and Evaluation, I", 2, 0, 1, 3, 2, "professional"),
                     ("HIS 216", "Human Anatomy and Physiology I", 1, 0, 2, 3, 3, "foundation"),
                     ("HIS 223", "Applied General Statistics", 2, 0, 1, 3, 3, "professional"),
                     ("GNS 213", "Introduction to Medical Sociology", 3, 0, 0, 3, 3, "general"),
                     ("GNS 228", "Research Methods I", 2, 0, 0, 2, 2, "general"),
                     ("GNS 201", "Use of English II", 2, 0, 0, 2, 2, "general"),
                     ("ENT 216", "Introduction to Entrepreneurship II", 2, 0, 1, 3, 3, "general")],
            (2, 2): [("HIS 215", "Fundamentals of Data Analysis", 1, 0, 1, 2, 2, "professional"),
                     ("HIM 221", "Electronic Health Records I", 1, 0, 1, 2, 2, "professional"),
                     ("HIM 222", "Hospital Statistics", 1, 0, 0, 1, 1, "professional"),
                     ("HIS 221", "Monitoring and Evaluation II", 1, 0, 0, 2, 1, "professional"),
                     ("HIS 222", "Legal and Ethical Aspects of HIM I", 2, 0, 0, 2, 2, "professional"),
                     ("HIM 223", "Research Project", 0, 0, 6, 6, 6, "project"),
                     ("GNS 202", "Communication in English II", 2, 0, 0, 2, 2, "general")],
        },
    },
    {
        "code": "CHE", "name": "Community Health Extension Workers (CHEW)", "slug": "community-health-chew",
        "department": ("Community Health", "CHE"),
        "award_title": "Diploma in Community Health (Community Health Extension Workers)",
        "regulatory_body": "Community Health Practitioners Registration Board of Nigeria (CHPRBN), with NBTE",
        "curriculum_reference": "CHPRBN Curriculum for Diploma in Community Health for CHEWs (June 2022)",
        "pdf": "Updated CHEW curriculum 2022.pdf",
        "duration_years": 3, "level_names": "Year One, Year Two, Year Three", "scheme": "chprbn",
        "ca": 30, "exam": 70, "min_total": 0, "max_total": 0, "icon": "bi-people", "order": 4,
        "summary": "The curriculum produces Community Health Extension Workers (CHEWs) with appropriate and adequate knowledge, skills, "
                   "attitude and competences for effective delivery of health care services at the Primary Healthcare level.",
        "goal": "To produce CHEWs with appropriate and adequate knowledge, skills, attitude and competences for effective delivery of "
                "health care services at the Primary Healthcare level.",
        "objectives": "Explain the Primary Health Care approach of the Nigerian Health System to the community\n"
                      "Carry out community mobilization for health action\n"
                      "Carry out community diagnosis and continuous health needs assessments with the community\n"
                      "Provide integrated Primary Health Care services, including maternal and child health and immunization\n"
                      "Manage clients according to Standing Orders and maintain high quality of care\n"
                      "Collect and collate monitoring and evaluation data for the National Health Management Information System",
        "entry_requirements": "WASCE, SSCE, NECO or GCE O/L with five (5) credits at not more than two sittings\n"
                              "Subjects must include English Language, Mathematics, Biology, Chemistry and Physics\n"
                              "Or: Junior Community Health Extension Worker (JCHEW) with 2 years' post-qualification experience, the above O'Level "
                              "requirement, registration with the CHPRBN and a valid practice licence",
        "structure_notes": "Three (3) academic years based on the policy of the CHPRBN, delivered as theory and practical in a ratio of 40:60, "
                           "with Supervised Clinical Experience (SCE) and Supervised Community-Based Experience (SCBE) recorded in a Log Book.",
        "assessment_notes": "Each course is assessed 30% continuous assessment (tests, quizzes, assignments) and 70% semester examination. Pass mark 50%.",
        "award_conditions": "Pass the final Professional and Practice Licensing Examination organised by the CHPRBN\n"
                            "Research Project supervised by the institution and assessed by the Board",
        "practicals": [
            ("sce", "Supervised Clinical Experience I (CHE 116)", 1, 2, "Year One, second semester", "90 hours",
             "Evaluation based on the field supervisor's report: punctuality, attendance, attitude to work, respect for authority, interest and technical competence."),
            ("sce", "Supervised Clinical Experience II (CHE 218)", 2, 2, "Year Two, second semester", "90 hours", "Log Book signed by designated supervisors."),
            ("scbe", "Supervised Community Based Experience (CHE 317)", 3, 1, "Year Three, first semester", "120 hours", "Log Book signed by designated supervisors."),
            ("project", "Research Project (CHE 312)", 3, 2, "Year Three, second semester", "90 hours", "Supervised by the institution and assessed by the Board."),
            ("licensing", "CHPRBN Professional and Practice Licensing Examination", 3, 2, "End of programme", "", ""),
        ],
        "courses": {
            (1, 1): [("CHE 101", "Professional Ethics", None, None, None, 15, 1, "professional"),
                     ("CHE 103", "Anatomy and Physiology I", None, None, None, 45, 2, "professional"),
                     ("CHE 105", "Social Behaviour Change Communication", None, None, None, 30, 2, "professional"),
                     ("CHE 107", "Human Nutrition", None, None, None, 30, 2, "professional"),
                     ("CHE 109", "Introduction to Primary Health Care", None, None, None, 30, 2, "professional"),
                     ("GNS 101", "Use of English", None, None, None, 30, 2, "general"),
                     ("GNS 103", "Citizenship Education", None, None, None, 15, 1, "general"),
                     ("GNS 105", "Introduction to Medical Psychology", None, None, None, 15, 1, "general"),
                     ("GNS 107", "Introduction to Medical Sociology", None, None, None, 30, 2, "general"),
                     ("BCH 101", "Introduction to Physical Chemistry", None, None, None, 15, 1, "foundation"),
                     ("EHT 101", "Introduction to Environmental Health", None, None, None, 30, 2, "foundation"),
                     ("FOT 101", "Geography", None, None, None, 15, 1, "foundation"),
                     ("COM 101", "Introduction to Computer", None, None, None, 30, 2, "foundation")],
            (1, 2): [("CHE 102", "Symptomatology", None, None, None, 30, 2, "professional"),
                     ("CHE 104", "Anatomy and Physiology II", None, None, None, 30, 2, "professional"),
                     ("CHE 106", "Reproductive Health", None, None, None, 30, 2, "professional"),
                     ("CHE 108", "Clinical Skills I", None, None, None, 45, 3, "professional"),
                     ("CHE 110", "Immunity and Immunization", None, None, None, 45, 2, "professional"),
                     ("CHE 112", "Control of Communicable Diseases", None, None, None, 30, 2, "professional"),
                     ("CHE 114", "Accident and Emergency", None, None, None, 30, 2, "professional"),
                     ("CHE 116", "Supervised Clinical Experience I", None, None, None, 90, 3, "clinical"),
                     ("CHE 118", "Care and Management of HIV/AIDS", None, None, None, 15, 1, "professional"),
                     ("GNS 102", "Communication in English", None, None, None, 30, 2, "general"),
                     ("STB 102", "Medical Laboratory Science Technology", None, None, None, 45, 3, "foundation")],
            (2, 1): [("CHE 201", "Anatomy and Physiology III", None, None, None, 30, 2, "professional"),
                     ("CHE 203", "Oral Health", None, None, None, 30, 2, "professional"),
                     ("CHE 205", "Community Mental Health", None, None, None, 30, 2, "professional"),
                     ("CHE 207", "Population Dynamics and Family Planning", None, None, None, 30, 2, "professional"),
                     ("CHE 209", "Child Health", None, None, None, 45, 3, "professional"),
                     ("CHE 211", "School Health Programme", None, None, None, 30, 2, "professional"),
                     ("CHE 213", "Control of Non-Communicable Diseases", None, None, None, 30, 2, "professional"),
                     ("CHE 215", "Community linkages and Development", None, None, None, 45, 3, "professional"),
                     ("CHE 217", "Occupational Health and Safety Education", None, None, None, 30, 2, "professional")],
            (2, 2): [("CHE 202", "Anatomy & Physiology IV", None, None, None, 30, 2, "professional"),
                     ("CHE 204", "Clinical Skills II", None, None, None, 90, 3, "professional"),
                     ("CHE 206", "Maternal Health", None, None, None, 105, 4, "professional"),
                     ("CHE 208", "Modified Essential New Board Care", None, None, None, 45, 3, "professional"),
                     ("CHE 210", "Community Ear, Nose and Throat Care (ENT)", None, None, None, 45, 3, "professional"),
                     ("CHE 212", "Primary/ Community Eye Care", None, None, None, 15, 1, "professional"),
                     ("CHE 214", "Use of Standing Orders", None, None, None, 75, 3, "professional"),
                     ("CHE 216", "Introduction to Pharmacology", None, None, None, 30, 2, "professional"),
                     ("CHE 218", "Supervised Clinical Experience II", None, None, None, 90, 4, "clinical"),
                     ("CHE 220", "Research Methodology", None, None, None, 30, 2, "professional")],
            (3, 1): [("CHE 301", "Care of the Older Persons", None, None, None, 15, 1, "professional"),
                     ("CHE 303", "Care of Persons with Special Needs", None, None, None, 30, 2, "professional"),
                     ("CHE 305", "Health Statistics", None, None, None, 30, 2, "professional"),
                     ("CHE 307", "Essential Medicines", None, None, None, 30, 2, "professional"),
                     ("CHE 309", "Human Resource for Health", None, None, None, 15, 1, "professional"),
                     ("CHE 311", "The Nigerian Health System", None, None, None, 30, 2, "professional"),
                     ("CHE 313", "Community Based New born Care", None, None, None, 45, 3, "professional"),
                     ("CHE 315", "Community Disaster and Complex Emergencies Management", None, None, None, 30, 2, "professional"),
                     ("CHE 317", "Supervised Community Based Experience (SCBE)", None, None, None, 120, 8, "community")],
            (3, 2): [("CHE 302", "Primary Health Care Management", None, None, None, 30, 2, "professional"),
                     ("CHE 304", "Referral System And Outreach Services", None, None, None, 30, 2, "professional"),
                     ("CHE 306", "Accounting System in Primary Health Care", None, None, None, 15, 1, "professional"),
                     ("CHE 308", "Health Management Information System", None, None, None, 30, 2, "professional"),
                     ("BUS 310", "Entrepreneurship Education", None, None, None, 30, 2, "general"),
                     ("CHE 312", "Research Project", None, None, None, 90, 4, "project")],
        },
    },
]

# Discrepancies found in the source documents (shown to administrators; nothing auto-corrected).
SOURCE_NOTES = [
    "ND Nutrition & Dietetics, ND I second semester: the table starts at S/N 2 and its printed total is 25 units, but the listed courses add up to 21 units — one course appears to be missing from the source document.",
    "ND Nutrition & Dietetics, ND I second semester: 'Citizenship Education II' is printed with code GNS 101 (same code as Use of English I). Kept as printed; confirm the correct code.",
    "ND Nutrition & Dietetics, GNS 202: practical hours printed as '12' (table total 8). Hours recorded as blank; credit units (2) unaffected.",
    "ND Health Information Management, ND II second semester: printed total is 18 units but the listed courses add up to 16 units.",
    "ND Public Health Technology: the curriculum gives no letter-grade table; the NBTE 9-band scale used by the other ND programmes is applied. Confirm with the Academic Board.",
    "ND Nutrition & Dietetics and ND HIM: the curricula do not specify a CA/exam split; 30/70 is configured initially.",
    "CHEW CHE 208 is printed as 'Modified Essential New Board Care' (probably 'Newborn Care'). Kept as printed; correct in Academic setup if confirmed.",
    "No course prerequisites are specified in any of the four curricula; none have been configured.",
]

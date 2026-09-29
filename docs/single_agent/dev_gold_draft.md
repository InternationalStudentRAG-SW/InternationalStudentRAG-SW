# 개발용 질문 정답 초안 (검토용)

- 자동 생성: `python -m evaluate.export_dev_gold` (원본은 `Backend/evaluate/dev_questions.py`)
- 상태: **초안**. 체크리스트 9절대로 원문 근거 승인은 팀이 한다. 틀린 곳은 dev_questions.py를 고치고 다시 생성.
- 기준 풀: 2026-09-29 수집한 첫 바퀴(검색 1회 + 1순위 청크 앞뒤 확장)

## D1 (T1) 한국어학당 수업료가 얼마예요?

- 확인할 점: 표 안의 값, 통화·산정 단위, 표가 청크에서 잘리는지 (partial/cut_at)
- 첫 바퀴 기대 다음 행동: answer / continue_search

| 칸 | 허용 상태 | 꼭 인용 (묶음 중 하나) | 인용 금지 |
|---|---|---|---|
| requested_value | supported | 어학당 안내 p2#c1 또는 어학당 안내 p2#c2 | 모집요강(한국어트랙) p19#c6<br>모집요강(한국어트랙) p20#c2<br>모집요강(한국어트랙) p20#c3<br>GKS지침(EN) p3#c0 |
| applicable_scope | supported | 어학당 안내 p2#c1 또는 어학당 안내 p2#c2 | - |

<details><summary>근거 청크 본문 (앞부분)</summary>

- **어학당 안내 p2#c1**: ## **Program outline**    ¦**Semester**<br>Four quarters(10 weeks per quarter)<br>**Hours**<br>20 hours × 10 weeks = 200 hours¦  ¦---¦  ¦**Days**<br>Mon – Fri (
- **어학당 안내 p2#c2**: ¦**Tuition Fee**<br>1,300,000 KRW per semester<br>※ Screening fee (50,000KRW) is a non-refundable initial payment due at the time of admission. ¦  ¦**Level and*
- **모집요강(한국어트랙) p19#c6**: ## **다. 등록금액**   ¦**계열**¦**수업료**<br>(단위: 원)¦**수업료**<br>(단위: 원)¦ ¦---¦---¦---¦ ¦¦**최초1학기**¦**최초1학기대상자를제외한**<br>**전체납부대상자**¦ ¦**인문·사회**¦3,476,700¦3,318,500¦ ¦**미디
- **모집요강(한국어트랙) p20#c2**: ## **1) 외국인우수신입생장학금**   ¦**구분**¦**구분**¦¦**수혜금액**¦**수혜조건**¦ ¦---¦---¦---¦---¦---¦ ¦**장학명**¦**자격요건**¦**종류**¦¦¦ ¦**외국인**<br>**우수신입생**<br>**장학금**<br>**A,B,C,D,E**¦*
- **모집요강(한국어트랙) p20#c3**: ¦¦¦**D**¦수업료40%¦동아한국어능력시험(Dong-A TOPIK) 3급이상소지자¦ ¦¦¦**E**¦수업료30%¦본교입학자격요건을갖춘신(편)입생중,<br>외국인우수신입생장학금A,B,C,D에해당되지않는자¦ ¦**DAU**<br>**외국인**<br>**우수신입생**<br>**장학금**<
- **GKS지침(EN) p3#c0**: provision applies only to the GKS recipient who has achieved 70% or higher of the passing score for the TOPIK level three (3).    - ⑤ A GKS recipient undergoing

</details>

**최종 기대**: answer
- 1,300,000 KRW per semester (한 학기 10주, 연 4학기)
- 전형료 50,000원은 환불 불가

**메모**
- 검색 1순위가 학부 장학금 표(수업료 %)였고 정답 청크는 2위. 1순위를 앵커로 한 확장은 헛돌았음
- 학부 등록금(p19#c6)·장학금 비율·GKS 50% 부담(p3#c0)을 어학당 수업료로 쓰면 오답
- 기준 시점: 청크 본문에 연도가 없고 파일명만 2026-2027. reference_time을 어떻게 볼지 팀 결정 필요

---

## D2 (T1) 동아대학교 2026년 가을학기 지원 기간이 언제예요?

- 확인할 점: 날짜, 기준 시점, 한국어·영어 트랙 갈래
- 첫 바퀴 기대 다음 행동: answer_by_condition / answer

| 칸 | 허용 상태 | 꼭 인용 (묶음 중 하나) | 인용 금지 |
|---|---|---|---|
| requested_value | supported | 모집요강(한국어트랙) p5#c0<br>모집요강(영어트랙) p5#c0 | - |
| applicable_scope | supported/partial | - | - |
| variation_notes | - | 모집요강(한국어트랙) p5#c1 | - |

- 활성화돼야 할 사용자 칸: track

<details><summary>근거 청크 본문 (앞부분)</summary>

- **모집요강(한국어트랙) p5#c0**: ## 1. 전형일정   ¦**구분**¦**일정**¦**일정**¦**3차**<br>**비고**¦**3차**<br>**비고**¦**3차**<br>**비고**¦ ¦---¦---¦---¦---¦---¦---¦ ¦¦**1차**¦**2차**¦¦¦¦ ¦**모집기간**¦**2026.4.1.(수) ~*
- **모집요강(영어트랙) p5#c0**: ## 1.  Admission Schedule    ¦**Process**¦**Dates**¦**Dates**¦**Remarks**¦  ¦---¦---¦---¦---¦  ¦¦**1st Round**¦**2nd Round**¦¦  ¦**Online**<br>**Application**¦2
- **모집요강(한국어트랙) p5#c1**: ## **※ 3차지원은국내체류자만가능함**   ※ 전형일정은사정에따라변동될수있음   - ※ 변동사항발생시국제교류과홈페이지공지예정(https://global.donga.ac.kr)

</details>

**최종 기대**: answer_by_condition
- 한국어트랙: 1차 2026.4.1~4.14, 2차 6.15~6.21, 3차 7.23~7.29 (3차는 국내 체류자만)
- 영어트랙: 1차 2026.4.1~4.14, 2차 6.15~6.21
- 전형 일정은 변동될 수 있음 (국제교류과 홈페이지 공지)

**메모**
- [팀 확인] '가을학기'를 학부 후기 입학으로 볼지, 어학당 2학기(8/31 시작, 지원 5.18~7.03)도 포함할지. 초안은 학부 기준

---

## D3 (T2) 유학생이 받을 수 있는 장학금 종류는 뭐가 있어요?

- 확인할 점: 여러 청크·문서에 흩어진 목록, '모든 종류' 단정 금지
- 첫 바퀴 기대 다음 행동: continue_search

| 칸 | 허용 상태 | 꼭 인용 (묶음 중 하나) | 인용 금지 |
|---|---|---|---|
| requested_list | partial | 모집요강(한국어트랙) p20#c2<br>모집요강(한국어트랙) p20#c5<br>모집요강(한국어트랙) p21#c0 | 모집요강(한국어트랙) p22#c2<br>GKS지침(KO) p2#c0 |

<details><summary>근거 청크 본문 (앞부분)</summary>

- **모집요강(한국어트랙) p20#c2**: ## **1) 외국인우수신입생장학금**   ¦**구분**¦**구분**¦¦**수혜금액**¦**수혜조건**¦ ¦---¦---¦---¦---¦---¦ ¦**장학명**¦**자격요건**¦**종류**¦¦¦ ¦**외국인**<br>**우수신입생**<br>**장학금**<br>**A,B,C,D,E**¦*
- **모집요강(한국어트랙) p20#c5**: ## **2) 외국인유학생국가장학금**   ¦**구분**¦**수혜기간**¦**수혜금액**¦**수혜조건**¦ ¦---¦---¦---¦---¦ ¦**동아특화분야**<br>**우수장학금**Ⅰ¦첫학기¦수업료전액<br>(입학금포함)¦아래학과외국인**신입학**특별전형합격자중학과추천자<br>-<br
- **모집요강(한국어트랙) p21#c0**: ## **나. 재학생장학금**   ¦¦**구분**¦**구분**¦**구분**¦¦**수혜금액**¦**수혜조건**¦**수혜조건**¦**수혜조건**¦**수혜조건**¦ ¦---¦---¦---¦---¦---¦---¦---¦---¦---¦---¦ ¦¦**장학명**¦**자격요건**¦¦**종류**¦¦¦
- **모집요강(한국어트랙) p22#c2**: ## **다. 유학생지원프로그램**   ¦**프로그램명**¦**프로그램내용**¦ ¦---¦---¦ ¦**유학생학습튜터링**¦외국인학부신/편입생과한국인재학생을多:1로매치하여외국인학부학교생<br>활안내및학업지원¦ ¦**유학생전공스터디그룹**¦학부유학생(2~4학년)들의전공학습지원을위한튜터링프
- **GKS지침(KO) p2#c0**: - 제3조(적용 대상) 이 지침의 적용 대상은 국립국제교육원(이하 “교육원”이라 한다)이 관리하는 장학사업으로 다음 각 호에 해당하는 사업에 선발된 장학생을 대상으로 한다. 1. 정부초청외국인장학생 교류지 원 사업   2. 한일 공동 고등교육 유학생 교류사업(석박사 학위과정)   - 제

</details>

**최종 기대**: answer (보유 자료 범위 명시)
- 신입생: 외국인우수신입생 A~E, DAU 외국인우수신입생 A~D, 동아특화분야 우수장학금 Ⅰ·Ⅱ
- 재학생: 외국인 성적우수 A~D, 근로장학금, TOPIK 장학금
- 영어트랙은 별도 장학금 (English Track Freshman Scholarship A~D)
- 첫 풀 밖에 있는 필요한 청크: 모집요강(한국어트랙) p20#c6, 모집요강(영어트랙) p14#c8, 모집요강(영어트랙) p14#c9

**메모**
- 동아특화분야 우수장학금 Ⅱ가 p20#c6에 있는데 첫 풀에 없음 → 목록이 끊긴 전형적인 partial (cut_at p20#c5)
- 영어트랙 모집요강의 장학금(p14)은 한국어 검색어로 안 잡힘
- 유학생 지원 프로그램(p22#c2)·GKS 적용 대상(p2#c0)은 장학금 종류가 아님

---

## D4 (T3) 입학 지원할 때 필요한 서류가 뭐예요?

- 확인할 점: 페이지를 넘어가는 서류 목록, 조건별 추가 서류, 신입/편입 갈래
- 첫 바퀴 기대 다음 행동: continue_search

| 칸 | 허용 상태 | 꼭 인용 (묶음 중 하나) | 인용 금지 |
|---|---|---|---|
| requested_documents | partial | 모집요강(한국어트랙) p13#c1<br>모집요강(한국어트랙) p13#c2 | Study in KOREA(KVAC 헤이그) p3#c5<br>Study in KOREA(KVAC 헤이그) p5#c5 |

- 활성화돼야 할 사용자 칸: admission_type

<details><summary>근거 청크 본문 (앞부분)</summary>

- **모집요강(한국어트랙) p13#c1**: ## **가. 필수제출서류**   ¦**순번**¦**제출서류**¦**제출서류**¦**구분**¦**구분**¦**비고**¦ ¦---¦---¦---¦---¦---¦---¦ ¦¦¦¦**신입**¦**편입**¦¦ ¦**1**¦입학지원서¦¦●¦●¦-<br>온라인접수후출력<br>(applydonga.
- **모집요강(한국어트랙) p13#c2**: 참조<br>-<br>아포스티유혹은한국영사확인¦ ¦**5**¦고등학교성적증명서¦¦●¦●¦-<br>유의사항바.’ 참조<br>-<br>고등학교전학년성적기재<br>-<br>아포스티유혹은한국영사확인¦ ¦**6**¦전적대학졸업(예정)증명서또는<br>재학증명서¦¦¦●¦-<br>‘유의사항마.’ 참조<
- **Study in KOREA(KVAC 헤이그) p3#c5**: ¦**3**¦One 3.5X4.5 cm picture taken in the past 6 months.  Please glue the photo on the Application Form. <br> 최근6개월이내촬영한3.5X4.5 cm사진. 사증발급신청서사진란에풀로부착. ¦  ¦**4*
- **Study in KOREA(KVAC 헤이그) p5#c5**: ## ➢ **필수제출서류 / Mandatory document to be submitted**    **1 Visa Application Form (Form no. 17) / 사증발급신청서 (제17호서식) e-signature not permitted/전자서명불가** Passport w

</details>

**최종 기대**: answer_by_condition
- 필수 13종 (6·7번 전적대학 서류는 편입만)
- 재정 주체가 본인이 아니면 재정보증확인서·수입증명·재직증명 추가
- 한국어·영어 외 언어 서류는 번역공증
- 첫 풀 밖에 있는 필요한 청크: 모집요강(한국어트랙) p13#c3, 모집요강(한국어트랙) p14#c1

**메모**
- 필수서류 표가 p13#c2의 8번에서 끊김 → 9~13번은 p13#c3 (cut_at p13#c2)
- Study in KOREA의 비자 서류는 입학 지원 서류가 아님
- [① 문제] ①이 conditional_documents·format_validity·country_exceptions를 not_triggered(비활성)로 둠. 문서를 보기 전이라 발동 여부를 알 수 없으므로 unresolved여야 함(체크리스트 1.2절)
- [팀 확인] 영어트랙 서류도 함께 안내할지

---

## D5 (T4) 기숙사 신청 방법을 알려주세요.

- 확인할 점: 자료에 절차가 없는 경우('추후 공지'). 절차를 지어내지 않고 partial_answer/no_evidence로 가는지
- 첫 바퀴 기대 다음 행동: continue_search

| 칸 | 허용 상태 | 꼭 인용 (묶음 중 하나) | 인용 금지 |
|---|---|---|---|
| step_sequence | partial/missing | - | 모집요강(영어트랙) p5#c4<br>모집요강(한국어트랙) p13#c1 |
| application_channel | - | - | 모집요강(영어트랙) p5#c4<br>모집요강(영어트랙) p5#c0 |

<details><summary>근거 청크 본문 (앞부분)</summary>

- **모집요강(영어트랙) p5#c4**: Register Online Application at (applydonga.accomsystem.co.kr) ↓ Log-in(sign up) and Choose your Undergraduate course ‘New’ ↓ Fill out the online application for
- **모집요강(한국어트랙) p13#c1**: ## **가. 필수제출서류**   ¦**순번**¦**제출서류**¦**제출서류**¦**구분**¦**구분**¦**비고**¦ ¦---¦---¦---¦---¦---¦---¦ ¦¦¦¦**신입**¦**편입**¦¦ ¦**1**¦입학지원서¦¦●¦●¦-<br>온라인접수후출력<br>(applydonga.
- **모집요강(영어트랙) p5#c0**: ## 1.  Admission Schedule    ¦**Process**¦**Dates**¦**Dates**¦**Remarks**¦  ¦---¦---¦---¦---¦  ¦¦**1st Round**¦**2nd Round**¦¦  ¦**Online**<br>**Application**¦2

</details>

**최종 기대**: answer_by_condition (학부/어학당) 또는 partial_answer
- 학부(한국어·영어트랙): 합격자 대상 추후 공지, 기숙사 홈페이지 hanlim.donga.ac.kr
- 어학당: 최종 합격 후 입국해서 기숙사 신청서 작성·기숙사비 납부
- 첫 풀 밖에 있는 필요한 청크: 어학당 안내 p4#c8, 모집요강(영어트랙) p16#c1

**메모**
- [중요] 체크리스트 5.2절은 '기숙사 신청 = 추후 공지뿐'이라고 했지만, 어학당 자료 p4#c8에 신청 절차가 있음. 첫 검색(한국어 검색어)이 영어 청크를 못 찾은 것
- 입학 지원 절차(ENT p5#c4)를 기숙사 절차로 쓰면 오답

---

## D6 (T5) GKS 장학생은 아르바이트할 수 있어?

- 확인할 점: 기준선. 학위과정/한국어연수 갈래, 예외 조항, 20시간·방학 한정
- 첫 바퀴 기대 다음 행동: answer_by_condition / continue_search

| 칸 | 허용 상태 | 꼭 인용 (묶음 중 하나) | 인용 금지 |
|---|---|---|---|
| rule | supported | GKS지침(EN) p10#c3<br>GKS지침(EN) p11#c0 | - |
| applicable_scope | supported | GKS지침(EN) p10#c3<br>GKS지침(EN) p11#c0 | - |
| conditions_limits | supported/partial | GKS지침(EN) p10#c3<br>GKS지침(EN) p10#c4 | - |
| exceptions_related | supported/partial | GKS지침(EN) p11#c2 또는 GKS지침(EN) p11#c3<br>GKS지침(EN) p11#c4 또는 GKS지침(EN) p11#c3 | - |
| approval_reporting | supported | GKS지침(EN) p11#c0<br>GKS지침(EN) p10#c4 | - |
| * | - | - | GKS지침(KO) p10#c1 |

- 활성화돼야 할 사용자 칸: gks_stage

<details><summary>근거 청크 본문 (앞부분)</summary>

- **GKS지침(EN) p10#c3**: A GKS recipient must meet the part-time employment requirements set by the Ministry of Justice and other relevant authorities and comply with the following crit
- **GKS지침(EN) p11#c0**: 3. A GKS recipient in a degree program may engage in part-time employment only where the president of the university grants approval upon determining that such 
- **GKS지침(EN) p10#c4**: Part-time employment shall be permitted only during vacation periods.  Such employment shall require prior approval from the president of the Korean language in
- **GKS지침(EN) p11#c2**: - C. Field training as part of a practical training semester program;    - D. Internship activities;    - E. Other activities permitted within the scope of empl
- **GKS지침(EN) p11#c3**: However, an exception may be granted if all of the following conditions are met:    - A. The recipient has received only one (1) academic warning;    - B. The r
- **GKS지침(EN) p11#c4**: 5. The exception under Subparagraph 4 shall not apply to GKS recipients who have received two (2) academic warnings.    - ③ A GKS recipient in a degree program 
- **GKS지침(KO) p10#c1**: - ④제3항에 따라 취업한 장학생이 학업을 지속하고 수학대학의 학적을 유지하는 경우에는 장학생 자격을 유지할 수 있으며, 장학금 지급 여부는 학업 이행 여부, 학업 성취도 및 대학의 의견 등을 종합적으로 고려하여 결정한다. - ⑤교육원장은 정부초청 외국인 장학생(GKS) 사업의 성과 분

</details>

**최종 기대**: answer_by_condition (gks_stage)
- 공통: 법무부 시간제 취업 요건 충족, 전공 학업 우선
- 한국어연수: 6개월 이수 후, 방학 중에만, 연수기관장 사전 승인 + 법무부 사전 허가. 진학 TOPIK 취득 시 학기 중 주 20시간 이내
- 학위과정: 총장 승인 시에만 (성적·출석·지도교수 의견 고려)
- 성적경고 받으면 원칙적으로 3(E) 활동 불가, 경고 1회 등 요건 충족 시 예외, 2회면 예외 없음
- 첫 풀 밖에 있는 필요한 청크: GKS지침(EN) p11#c1

**메모**
- 이번 풀에는 예외 요건 A~C 전체(p11#c3)가 있음 (오전 live 풀과 다름: 검색어가 조금 달랐음)
- 허용 활동 목록 A·B(교내 근로, 연구)는 p11#c1에 있고 첫 풀에 없음 → conditions_limits는 partial도 허용
- KO p10#c1은 동문 조사·시행일 등 잡음

---

## D7 (T6) 휴학 기간이 끝났는데 복학 안 하면 어떻게 돼요?

- 확인할 점: 결과·제재, GKS 지침인지 학칙인지 적용 범위
- 첫 바퀴 기대 다음 행동: continue_search / partial_answer / answer_by_condition

| 칸 | 허용 상태 | 꼭 인용 (묶음 중 하나) | 인용 금지 |
|---|---|---|---|
| event_trigger | supported | GKS지침(KO) p7#c0 | - |
| consequence | supported | GKS지침(KO) p6#c1 | 모집요강(한국어트랙) p18#c1<br>GKS지침(EN) p7#c3 |
| applicable_scope | partial/supported | - | - |

- 활성화돼야 할 사용자 칸: gks_status

<details><summary>근거 청크 본문 (앞부분)</summary>

- **GKS지침(KO) p7#c0**: 3. 수학기관이 정한 등록 기간 내에 등록하지 않는 경우   4. 수학기관이 정한 학기 시작일 이후 정당한 사유 없이 입국하지 않는 경우   5. 휴학 기간 종료 후 정당 한 사유 없이 복학원서를 제출하지 않은 경우   6. 제12조제3항에 명시된 휴학 기간을 초과한 경우   7. 외국
- **GKS지침(KO) p6#c1**: - 제18조(경고) 다음 각 호의 어느 하나에 해당하는 경우, 교육원장은 해당 장학생을 경고 조치한다. 1. 한국어연수 기간 중 무단결석일이 연속하여 3일 이상이거나 월 누계 5일 이상인 경우 이 경우 출결의 세부기준(지각, 조퇴, 결석의 환산 기준 등)은 한국어연수기관 내부 규 정에 
- **모집요강(한국어트랙) p18#c1**: - **사. 전형에관한모든공지사항은본교국제교류과홈페이지를통해공지합니다. 인터넷원서접수시연락가능한연 락처와E-mail 주소를정확하게입력하지않거나지원자와연락이되지않아불이익이발생한경우본교는책임을 지지않습니다.* *   - ‧   - 아. 다음사항에해당하는경우에는입학이후라도합격또는입학을취소하고
- **GKS지침(EN) p7#c3**: 2. Failure to achieve the required grades by semester, (70/100) for associate and undergraduate programs, (80/100) for master’s and doctoral programs;    3. Tem

</details>

**최종 기대**: partial_answer (GKS 한정 안내 + 일반 학생 기준은 보유 자료 없음)
- GKS 장학생: 휴학 종료 후 정당한 사유 없이 복학원서 미제출 → 장학생 자격상실 (제19조 5호)
- 복학 신고는 휴학 종료 1개월 전까지 (제13조)
- GKS가 아닌 학생의 기준은 학칙 사항이며 현재 자료에 없음 (제23조 준용 규정)

**메모**
- [중요] 근거가 모두 GKS 지침. 질문은 GKS를 말하지 않았으므로(general) 일반 학생 규정처럼 답하면 안 됨 (체크리스트 5.3절 2항)
- 자격상실 조항 제목(제19조)은 p6#c1 끝에, 해당 호(5호)는 p7#c0에 있음 → 두 청크를 같이 봐야 결과가 확정됨
- 첫 학기 휴학 불가(KOT p18#c1)·경고 사유(GE p7#c3)는 이 사건의 결과가 아님

---

## D8 (T5+T3+T4) 저 GKS 장학생인데 아르바이트 해도 돼요? 된다면 어떤 서류를 어디에 내야 해요?

- 확인할 점: 복합 질문, 본인 사례(personal) → 갈리는 조건이 있으면 ask_clarification
- 첫 바퀴 기대 다음 행동: continue_search

| 칸 | 허용 상태 | 꼭 인용 (묶음 중 하나) | 인용 금지 |
|---|---|---|---|
| rule | supported | GKS지침(EN) p10#c3<br>GKS지침(EN) p11#c0 | - |
| requested_documents | missing/unchecked | - | GKS지침(EN) p3#c1<br>GKS지침(EN) p6#c2 |
| submission_method | - | - | GKS지침(EN) p3#c1<br>GKS지침(EN) p6#c2 |

- 활성화돼야 할 사용자 칸: gks_stage

<details><summary>근거 청크 본문 (앞부분)</summary>

- **GKS지침(EN) p10#c3**: A GKS recipient must meet the part-time employment requirements set by the Ministry of Justice and other relevant authorities and comply with the following crit
- **GKS지침(EN) p11#c0**: 3. A GKS recipient in a degree program may engage in part-time employment only where the president of the university grants approval upon determining that such 
- **GKS지침(EN) p3#c1**: - ⑥ A GKS recipient who has been granted an extension of Korean language program period under Paragraph 4  must obtain at least TOPIK Level 3 and meet the admis
- **GKS지침(EN) p6#c2**: The applicant must receive approval from the president of Korean language institution.  In urgent cases, such as a family member's death, the recipient may appl

</details>

**최종 기대**: ask_clarification (gks_stage) 후 답변, 서류 목록은 보유 자료로 확인 불가
- 승인 주체: 학위과정은 총장, 한국어연수는 연수기관장 + 법무부
- 시간제 취업 허가 서류 목록은 현재 자료에 없음 (출입국·학교 확인 필요)

**메모**
- 결석 서류(GE p3#c1)·일시출국 승인(GE p6#c2)을 아르바이트 서류로 쓰면 오답
- [① 문제] 추가 유형 T4 때문에 step_sequence·application_channel 등이 필수로 추가돼 칸이 16개. '어디에 내?'는 T3 submission_method로 충분할 수 있음 → 검색 예산 낭비 가능

---

## D9 (T3) What documents do I need to apply for a student visa?

- 확인할 점: 영어 질문, 관할이 제한된 비자 자료(체크리스트 5.3절)
- 첫 바퀴 기대 다음 행동: answer_by_condition / continue_search / partial_answer

| 칸 | 허용 상태 | 꼭 인용 (묶음 중 하나) | 인용 금지 |
|---|---|---|---|
| requested_documents | supported/partial | 어학당 안내 p4#c1<br>어학당 안내 p4#c2 | 어학당 안내 p3#c7 |

- 활성화돼야 할 사용자 칸: program

<details><summary>근거 청크 본문 (앞부분)</summary>

- **어학당 안내 p4#c1**: ## **D-4 (Language Course student visa)**    - A. Applicants: a student who wants to enroll for a period of 6 months or longer    - B. Where to Apply: Overseas 
- **어학당 안내 p4#c2**: - A graduation certificate of the most recently attended school    - Proof of Financial Capability (at least USD 8,000 per year): Parents’ proof of income and c
- **어학당 안내 p3#c7**: ¦**Documents**¦**Note**¦  ¦---¦---¦  ¦A completed application form¦Download at http://global.donga.ac.kr¦  ¦A copy of the student’s certificate of graduation¦Ne

</details>

**최종 기대**: answer_by_condition (어학연수 D-4 / 학위 D-2) + 관할 한정 안내
- D-4(어학연수): 사증발급신청서, 여권 사본, 사진, 수수료, 입학허가서·수업료 확인서, 최종학교 졸업증명, 재정능력 입증(연 USD 8,000 이상), 잔고증명(KRW 8,000,000 이상), 결핵검사 확인서
- D-2 서류 목록은 KVAC 헤이그(네덜란드) 신청 기준 자료뿐 → 다른 국가 신청자에게 그대로 안내하면 안 됨

**메모**
- Study in KOREA 자료는 'KVAC THE HAGUE 2024'(p1#c3), 네덜란드 거주 조건·유로 금액 → 체크리스트 5.3절 1항 사례로 확인됨
- 어학당 입학 지원 서류(KLC p3#c7)는 비자 서류가 아님
- [① 문제] D4와 같이 conditional_documents를 not_triggered로 둠 (결핵·재정 증명은 조건부 서류)

---

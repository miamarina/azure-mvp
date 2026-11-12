# Assignment 1: Preliminary scenario and literature survey

> Working transcription of [the submitted PDF](Assignment_1_Group_15.pdf). Formatting, line wrapping, and typographic punctuation are normalized; page numbers and repeated footers are omitted. Content and KPI targets are preserved. The PDF remains the authoritative submission.

**Project Group:** 15  
**Team Members:** Gabriel Gander, Jonas Hirsch, Julian Lampert, Marina Mitrovic, Sarp Bora Polat

## Business Use Case: Lecture Scriptum Generator

### Setting

At our fictional university: lectures are recorded and published online so students can rewatch them. A recording typically spans 90 minutes and one course easily collects about 20 hours of lecture recordings per semester.

### Target audience

The main users are students who catch up on missed lectures, look up specific topics or revise for exams. Lecturers also benefit, since they get a script of their course without extra work.

### Problem

There are no official scripts and the slides cover only selected topics. If a key concept is explained between minutes 42 and 45 of the third recording, students must search by hand to find it and writing their own notes takes even longer.

As a result: many give up, valuable explanations go unused and revision is slow.

### Solution

We build a serverless application that automatically generates a scriptum from each lecture recording: a written, structured version of the lecture in which every passage links back to the matching minute in the video.

The application responds to two categories of events:

- **Video upload:** uploading a lecture video initiates a processing workflow:
  1. The audio is extracted and split into chunks.
  2. The chunks are transcribed in parallel, then merged into one transcript with timestamps.
  3. An LLM will structure the transcript into chapters and add a summary and key terms.
  4. The finished script is published as a static web page without a running server.
- **Student request:** Students are able to open the scriptum in the browser and search for keywords in all lectures, jumping directly to the matching passage in the video.

Optional extensions, if time allows:

- An LLM chat interface, which is accessible from the course page. It provides answers to questions based on the generated script.
- The system is also able to extract slide text from video frames (OCR).

For the purposes of development and evaluation, we utilise publicly available lecture recordings, such as those found on MIT OpenCourseWare, as a source of input.

### Value Proposition

The main value is faster and easier revision. Students can search for a topic, read the relevant explanation and jump directly to the matching moment in the video. This reduces the time spent searching through recordings or writing everything down manually.

The scriptum also captures spoken explanations and examples that may be missing from the slides. Chapters, summaries and key terms help students navigate the material, while the text format offers another way to study for those who find long videos difficult to follow.

Our USP is the direct connection between the structured text and the original recording. Students get a readable version of the lecture and can return to the full explanation whenever they need more context.

### Why serverless?

Lecture processing happens in bursts. Several recordings may be uploaded around the same time, followed by periods with little or no activity. Serverless fits this pattern because compute resources run when work arrives, keeping idle compute costs low. Storage and external service costs still apply.

Each upload starts a workflow that coordinates audio extraction, transcription and scriptum generation. Splitting the audio into smaller chunks allows transcription to run in parallel. The workflow tracks progress and retries failed steps, while a queue holds uploads until processing capacity is available.

Managed services also reduce the work needed to maintain servers. Once generated, the scriptum is served as a static web page, so reading it does not require the processing workflow to run again.

## KPIs

We introduce business and technical KPIs to show how well this solution has delivered what it promised. Each KPI tests one of the reasons why we chose a serverless architecture. All of these KPI targets are initial estimates and may be changed after the first test runs.

### Business KPIs

- **Cost per lecture hour:** the total cost of processing one hour of lecture video end to end, including all function invocations, the transcription and LLM services, workflow steps and storage writes. Long-term storage is excluded, since it is reported separately under idle cost.
  - **Target:** Below €1 per lecture hour.
- **Time to scriptum:** the time from the upload event until the scriptum can be retrieved by students, measured as the 95th percentile over all test lectures.
  - **Target:** Below 30 minutes for a 90-minute lecture.
- **Idle cost:** the monthly cost when no lectures are uploaded.
  - **Target:** Compute cost should be close to zero (below €1 per month); storage and database costs are reported separately in € per GB-month.
- **Cost per question (only if implemented):** the total cost of answering one student question, including the chat function, the passage search and the LLM API call.
  - **Target:** Below €0.01 per question.

### Technical KPIs

- **Transcript accuracy:** According to Radford et.al, the word error rate (WER) metric is used to evaluate the speech recognition output (2022, Sec. 3.2). We measure transcript accuracy of our transcripts compared to lectures with verified subtitles.
  - **Target:** WER below 15%. We also compare chunked and unchunked transcription to check that splitting the audio does not reduce accuracy.
  - **Computation methodology:** WER = (Substitution + Deletion + Insertion) ÷ n, where n is the number of words in the reference text.
- **Throughput at peak:** the 95th-percentile processing time per lecture when 5 lectures are uploaded at the same time, compared to the processing time of a single lecture.
  - **Target:** below 1.5 times the single-lecture processing time.
- **Parallel speedup:** the speed-up T(1) / T(n) when one lecture is transcribed by n parallel functions (n = 1, 2, 5, 10, 20), together with the cost at each n.
  - **Target:** a speedup of at least 5 at n = 10, with less than 10% additional cost.
- **Answer time under peak (only if implemented):** The 95th percentile time from sending a question to receive the full answer, measured at normal traffic and at 50 times normal traffic.
  - **Target:** below 5 seconds at peak.

## Papers/Scientific Backing

ATS (Tuna et al., 2024) is a fully serverless AWS service for transcribing social science interviews. The audio is batched via SQS and processed by Lambda functions using Amazon Transcribe. The Transcribe JSON output (with speaker labels, language, timestamps and per-word confidence) is then converted into a DOCX transcript. The infrastructure is all defined as code and quality is checked by comparing the automated transcripts to the manually transcribed ones.

"0.01 Cent per Second" (N. Pinyo et al., 2023) achieves cost savings by replacing the managed speech-to-text APIs with a self-hosted model. It's a combination of serverless, preemptible instances, batching and audio segmentation and achieves essentially the same level of accuracy at a fraction of the cost.

Risco & Moltó (2021) work around Lambda's 15 minute limit and lack of GPUs by handing the jobs off to AWS Batch which autoscales an ECS/EC2 cluster down to zero.

InstaScript (Manjula Devi C. et al., 2025) uses Whisper for speech to text, BART-Large-CNN for summarisation and FPDF for PDF output.

## Appendix: References

### Reference implementations

- A Serverless Framework example aws-node-simple-transcribe-s3 (S3 -> Lambda -> Transcribe)
- farski/serverless-transcribe (web UI, EventBridge, email delivery, SAM)
- Gupta (2023): A dev.to tutorial (Go + CDK).

None of them do batching or document output

### References

- Tuna, Walsh, Meanwell, Berg (2024). Automated Transcription Service: Enabling Transcription at Scale for Social Science Research. PEARC '24. [DOI](https://doi.org/10.1145/3626203.3670545).
- N. Pinyo et al. (2023). 0.01 Cent per Second: Developing a Cloud-based Cost-effective Audio Transcription System for an Online Video Learning Platform. JCSSE 2023. [DOI](https://doi.org/10.1109/JCSSE58229.2023.10201942).
- Risco & Moltó (2021). GPU-Enabled Serverless Workflows for Efficient Multimedia Processing. Applied Sciences 11(4). [DOI](https://doi.org/10.3390/app11041438).
- Manjula Devi C. et al. (2025). InstaScript: Convert Voice Notes to Summarized Smart Notes using NLP. ICSCN 2025. [DOI](https://doi.org/10.1109/ICSCN67106.2025.11308439).
- Radford et al. (2022). Robust Speech Recognition via Large-Scale Weak Supervision. arXiv:2212.04356v1 [eess.AS]. [Paper](https://arxiv.org/pdf/2212.04356).
- Serverless Framework (n.d.). Simple AWS Transcribe example (Node.js). GitHub. [Repository](https://github.com/serverless/examples/tree/v4/aws-node-simple-transcribe-s3).
- farski (n.d.). serverless-transcribe. GitHub. [Repository](https://github.com/farski/serverless-transcribe).
- Gupta (2023). Build a Serverless Application for Audio to Text conversion. dev.to. [Article](https://dev.to/aws/use-go-with-aws-lambda-and-amazon-transcribe-to-build-a-speech-to-text-converter-1j36).
- Wikipedia (n.d.). Word error rate. [Article](https://en.wikipedia.org/wiki/Word_error_rate).

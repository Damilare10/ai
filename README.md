# Smart Reply Agent

An intelligent Twitter/X auto-reply system powered by Google Gemini AI. This application automatically scrapes tweets, generates contextual replies, and posts them with human review.

## 🚀 Features

- **Batch Processing**: Process multiple tweet URLs simultaneously
- **AI-Powered Replies**: Generate contextual, tone-aware replies using Google Gemini
- **Review Queue**: Human-in-the-loop approval before posting
- **Analytics Dashboard**: Track reply statistics and success rates
- **Rate Limiting**: Built-in protection against API rate limits
- **Retry Logic**: Automatic retry with exponential backoff for failed requests
- **Comprehensive Logging**: Detailed logging with rotation for debugging

## 📋 Prerequisites

- Python 3.8+
- Twitter Developer Account with API access
- Google Gemini API key

## 🔧 Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd aireply
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` and add your credentials:
   - Twitter API credentials (API Key, Secret, Access Token, etc.)
   - Google Gemini API key

## 🚀 Usage

1. **Start the application**
   ```bash
   python main.py
   ```

2. **Access the dashboard**
   Open your browser and navigate to: `http://localhost:8000`

3. **Process tweets**
   - Paste tweet URLs in the batch input field
   - Select the desired tone (Professional, Casual, Witty, Friendly)
   - Click "Start Processing"
   - Review generated replies in the queue
   - Approve or discard each reply

## 📁 Project Structure

```
aireply/
├── main.py              # FastAPI application with API endpoints
├── config.py            # Configuration management (environment variables)
├── scraper.py           # Tweet scraping logic (Tweepy)
├── ai_agent.py          # AI reply generation (Google Gemini)
├── poster.py            # Tweet posting logic (Twitter API)
├── utils.py             # Database and utility functions
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variables template
├── .gitignore           # Git ignore rules
├── static/              # Frontend files
│   ├── index.html       # Dashboard UI
│   ├── dashboard.css    # Styles
│   └── dashboard.js     # Frontend logic
└── history.db           # SQLite database (auto-created)
```

## 🔒 Security

- **Environment Variables**: All sensitive credentials are stored in `.env` (gitignored)
- **Rate Limiting**: API endpoints are rate-limited to prevent abuse
- **CORS Protection**: Configurable allowed origins
- **Input Validation**: Pydantic models validate all incoming requests

## 🛠️ API Endpoints

- `GET /health` - Health check endpoint
- `GET /api/stats` - Get application statistics
- `GET /api/history` - Get reply history
- `GET /api/logs` - Get recent system logs
- `POST /api/scrape` - Scrape tweet content
- `POST /api/generate` - Generate AI reply
- `POST /api/post` - Post reply to Twitter

## 📊 Rate Limits

- Scraping: 10 requests/minute
- Generation: 15 requests/minute
- Posting: 5 requests/minute
- Stats/History: 20-30 requests/minute

## 🐛 Troubleshooting

### Database Issues
- Delete `history.db` and restart the application to recreate tables

### API Rate Limits
- Twitter API has strict rate limits. The application includes retry logic and cooldown periods
- Consider upgrading your Twitter API tier for higher limits

### Environment Variables Not Loading
- Ensure `.env` file exists in the project root
- Check that all required variables are set (see `.env.example`)

## 📝 Logging

Logs are stored in:
- `app.log` - Application logs with rotation (max 10MB, 5 backups)
- Console output for real-time monitoring

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📄 License

[Your License Here]

## 🙏 Acknowledgments

- Google Gemini for AI capabilities
- Twitter API for social media integration
- FastAPI for the web framework

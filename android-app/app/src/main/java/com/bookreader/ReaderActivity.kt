package com.bookreader

import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.bookreader.databinding.ActivityReaderBinding
import java.io.File

class ReaderActivity : AppCompatActivity() {

    private lateinit var binding: ActivityReaderBinding
    private var currentPage = 0
    private var totalPages = 0
    private var bookPath = ""
    private var bookType = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityReaderBinding.inflate(layoutInflater)
        setContentView(binding.root)

        bookPath = intent.getStringExtra("book_path") ?: ""
        bookType = intent.getStringExtra("book_type") ?: "txt"

        setupToolbar()
        loadBook()
        setupControls()
    }

    private fun setupToolbar() {
        setSupportActionBar(binding.toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        binding.toolbar.setNavigationOnClickListener {
            finish()
        }
    }

    private fun loadBook() {
        when (bookType) {
            "pdf" -> loadPdf()
            "epub" -> loadEpub()
            "txt" -> loadTxt()
        }
    }

    private fun loadPdf() {
        binding.pdfView.fromUri(Uri.parse(bookPath))
            .enableSwipe(true)
            .swipeHorizontal(true)
            .enableDoubletap(true)
            .defaultPage(0)
            .enableAnnotationRendering(true)
            .password(null)
            .scrollHandle(null)
            .enableAntialiasing(true)
            .spacing(0)
            .autoSpacing(false)
            .fitEachPage(false)
            .pageSnap(true)
            .pageFling(true)
            .nightMode(false)
            .load()
        
        totalPages = binding.pdfView.pageCount
        updatePageInfo()
    }

    private fun loadEpub() {
        // TODO: Implement EPUB reading using epublib
        Toast.makeText(this, "EPUB reading not yet implemented", Toast.LENGTH_SHORT).show()
    }

    private fun loadTxt() {
        try {
            val inputStream = contentResolver.openInputStream(Uri.parse(bookPath))
            val text = inputStream?.bufferedReader()?.use { it.readText() } ?: "无法读取文件"
            
            binding.txtContent.text = text
            totalPages = 1
            updatePageInfo()
        } catch (e: Exception) {
            Toast.makeText(this, "读取失败: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    private fun setupControls() {
        binding.btnPrev.setOnClickListener {
            if (currentPage > 0) {
                currentPage--
                goToPage(currentPage)
            }
        }

        binding.btnNext.setOnClickListener {
            if (currentPage < totalPages - 1) {
                currentPage++
                goToPage(currentPage)
            }
        }
    }

    private fun goToPage(page: Int) {
        when (bookType) {
            "pdf" -> binding.pdfView.jumpTo(page)
        }
        currentPage = page
        updatePageInfo()
    }

    private fun updatePageInfo() {
        binding.txtPageInfo.text = "第 ${currentPage + 1} 页 / 共 $totalPages 页"
    }
}
